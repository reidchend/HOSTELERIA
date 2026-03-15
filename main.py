# main.py  ── arquitectura de contenedor persistente
#
# La página se construye UNA SOLA VEZ tras el login.
# Los cambios de vista solo intercambian el contenido de _zona_contenido,
# dejando intactos la barra superior y las tarjetas de resumen.
# Esto elimina el parpadeo y la reconstrucción brusca de la interfaz.

import flet as ft
from sqlalchemy import func
from database.connection import inicializar_bd, SesionLocal
from database.models import Habitacion, EstadoHabitacion, Estadia, Huesped
from modules.auth.login import PantallaLogin
from modules.rooms.management import GridHabitaciones
from modules.rooms.details import DialogoDetallesHabitacion
from utils.helpers import cargar_configuracion_bd
from modules.finance.cash_opening import DialogoAperturaTurno


def principal(pagina: ft.Page):
    """
    Función principal de la aplicación.
    Configura la página, inicializa la BD y lanza la pantalla de login.

    ARQUITECTURA DE LAYOUT PERSISTENTE:
    La interfaz se construye una sola vez (_construir_interfaz_app) y
    nunca vuelve a hacerse pagina.clean() mientras el usuario esté logueado.
    Los cambios de vista operan sobre _zona_contenido exclusivamente,
    dejando inmóviles la barra superior y las tarjetas de resumen.
    """
    # ── Configuración de la ventana ─────────────────────────────────────────
    pagina.title        = "Hotel Management System"
    pagina.theme_mode   = ft.ThemeMode.LIGHT
    pagina.padding      = 0
    pagina.spacing      = 0
    pagina.window.width      = 1400
    pagina.window.height     = 900
    pagina.window.min_width  = 1200
    pagina.window.min_height = 700

    # ── Inicializar BD y cargar configuración ───────────────────────────────
    inicializar_bd()

    sesion_inicio = SesionLocal()
    try:
        config_inicial = cargar_configuracion_bd(sesion_inicio)
    except Exception as error:
        print(f"Error cargando configuración: {error}")
        config_inicial = {}
    finally:
        sesion_inicio.close()

    # ── Estado global de la aplicación ─────────────────────────────────────
    estado_app = {
        "usuario_activo": None,
        "tasa_cambio":    float(config_inicial.get("exchange_rate", 35.5)),
        "nombre_hotel":   config_inicial.get("hotel_name", "Mi Hotel"),
        "habitacion_sel": None,
        "vista_activa":   "dashboard",
    }

    # ════════════════════════════════════════════════════════════════════════
    # REFERENCIAS A WIDGETS PERSISTENTES
    #
    # Estos objetos se crean una vez y viven durante toda la sesión.
    # Al cambiar de vista, solo se modifica .content de _zona_contenido
    # y se llama a .update() — el resto del árbol de widgets no se toca.
    # ════════════════════════════════════════════════════════════════════════

    # Zona intercambiable: única parte del layout que cambia entre vistas
    _zona_contenido = ft.Container(expand=True)

    # Panel lateral de pendientes — se instancia después del login


    # Row de tarjetas de resumen — se actualiza reemplazando sus .controls
    _fila_tarjetas = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=15,
    )
    _contenedor_tarjetas = ft.Container(
        content=_fila_tarjetas,
        padding=20,
    )

    # Botón de navegación con referencia directa para cambiar texto/ícono in-place
    _btn_nav = ft.ElevatedButton(
        style=ft.ButtonStyle(
            color=ft.Colors.BLUE_700,
            bgcolor=ft.Colors.BLUE_50,
            shape=ft.RoundedRectangleBorder(radius=8),
        ),
    )

    # ════════════════════════════════════════════════════════════════════════
    # LÓGICA DE NEGOCIO
    # ════════════════════════════════════════════════════════════════════════

    def obtener_estadisticas_habitaciones() -> dict:
        """Conteo de habitaciones por estado en una única consulta GROUP BY."""
        sesion = SesionLocal()
        try:
            resultados = (
                sesion.query(Habitacion.estado, func.count(Habitacion.id))
                .group_by(Habitacion.estado)
                .all()
            )
            conteos = {estado: cantidad for estado, cantidad in resultados}
            return {
                "total":         sum(conteos.values()),
                "libres":        conteos.get(EstadoHabitacion.FREE,        0),
                "ocupadas":      conteos.get(EstadoHabitacion.OCCUPIED,    0),
                "reservadas":    conteos.get(EstadoHabitacion.RESERVED,    0),
                "limpieza":      conteos.get(EstadoHabitacion.CLEANING,    0),
                "mantenimiento": conteos.get(EstadoHabitacion.MAINTENANCE, 0),
            }
        except Exception as error:
            print(f"Error al obtener estadísticas: {error}")
            return {k: 0 for k in ["total", "libres", "ocupadas", "reservadas", "limpieza", "mantenimiento"]}
        finally:
            sesion.close()

    def al_hacer_clic_habitacion(habitacion):
        """Decide qué módulo abrir según el estado de la habitación clicada."""
        if habitacion.estado == EstadoHabitacion.FREE:
            from modules.rooms.checkin import DialogoCheckIn
            DialogoCheckIn(pagina, habitacion, al_completar=refrescar_grid_y_tarjetas).mostrar()

        elif habitacion.estado == EstadoHabitacion.CLEANING:
            def marcar_libre(_):
                from database.connection import SesionLocal
                from database.models import Habitacion as _Hab
                pagina.close(dlg_limpieza)
                sesion = SesionLocal()
                try:
                    hab_bd = sesion.get(_Hab, habitacion.id)
                    hab_bd.estado = EstadoHabitacion.FREE
                    sesion.commit()
                    refrescar_grid_y_tarjetas()
                    pagina.open(ft.SnackBar(
                        ft.Text(f"Hab. {habitacion.numero} marcada como DISPONIBLE"),
                        bgcolor=ft.Colors.GREEN_700,
                    ))
                except Exception as err:
                    sesion.rollback()
                    pagina.open(ft.SnackBar(ft.Text(str(err)), bgcolor=ft.Colors.RED_700))
                finally:
                    sesion.close()

            dlg_limpieza = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.CLEANING_SERVICES, color=ft.Colors.CYAN_700),
                    ft.Text(f"Hab. {habitacion.numero} — En Limpieza"),
                ], spacing=8),
                content=ft.Text(
                    "¿La habitación ya está lista?\n"
                    "Al confirmar pasará al estado DISPONIBLE.",
                    size=13,
                ),
                actions=[
                    ft.TextButton("Cancelar",
                                  on_click=lambda _: pagina.close(dlg_limpieza)),
                    ft.ElevatedButton(
                        "Marcar como Disponible",
                        icon=ft.Icons.CHECK_CIRCLE,
                        bgcolor=ft.Colors.GREEN_700, color="white",
                        on_click=marcar_libre,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            pagina.open(dlg_limpieza)

        elif habitacion.estado == EstadoHabitacion.OCCUPIED:
            # Se pasa al_actualizar_grid para que el diálogo de detalles pueda
            # notificar al dashboard cuando cambia algo (renovación, cargo extra,
            # cobro), actualizando las tarjetas y el grid sin reconstruir nada más.
            DialogoDetallesHabitacion(
                pagina, habitacion,
                al_solicitar_checkout=iniciar_checkout,
                al_actualizar_grid=refrescar_grid_y_tarjetas,
            ).mostrar()

    def iniciar_checkout(habitacion):
        """Lanza el wizard de Check-Out con validación financiera completa."""
        from modules.rooms.checkout import CheckOutWizard
        CheckOutWizard(
            pagina, habitacion,
            al_completar=lambda _: refrescar_grid_y_tarjetas(),
        ).mostrar()

    # ════════════════════════════════════════════════════════════════════════
    # ACTUALIZACIÓN QUIRÚRGICA DE LA INTERFAZ
    #
    # Ninguna de estas funciones llama a pagina.clean() ni pagina.add().
    # Cada una opera sobre el subárbol mínimo necesario.
    # ════════════════════════════════════════════════════════════════════════

    def _construir_tarjeta(etiqueta, valor, color, subtexto):
        return ft.Card(content=ft.Container(
            content=ft.Column([
                ft.Text(etiqueta, size=12, color=ft.Colors.GREY_700),
                ft.Text(str(valor), size=28, weight=ft.FontWeight.BOLD, color=color),
                ft.Text(subtexto, size=10, color=ft.Colors.GREY_600),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
            padding=10, width=140,
        ))

    def actualizar_tarjetas_resumen():
        """
        Refresca únicamente los números dentro del Row de tarjetas.
        Costo visual: cero parpadeo porque solo se reemplazan los hijos del Row.
        """
        stats = obtener_estadisticas_habitaciones()
        _fila_tarjetas.controls = [
            _construir_tarjeta("Total",         stats["total"],         ft.Colors.BLACK,  "habitaciones"),
            _construir_tarjeta("Libres",        stats["libres"],        ft.Colors.GREEN,  "disponibles"),
            _construir_tarjeta("Ocupadas",      stats["ocupadas"],      ft.Colors.RED,    "con huéspedes"),
            _construir_tarjeta("Limpieza",      stats["limpieza"],      ft.Colors.BLUE,   "en aseo"),
            _construir_tarjeta("Mantenimiento", stats["mantenimiento"], ft.Colors.PURPLE, "fuera de servicio"),
        ]
        _fila_tarjetas.update()

    def _mostrar_dashboard():
        """Inyecta el grid de habitaciones en la zona intercambiable."""
        cuadricula = GridHabitaciones(estado_app, al_hacer_clic_habitacion)
        _zona_contenido.content = ft.Container(
            content=cuadricula.construir(),
            expand=True,
            padding=ft.padding.symmetric(horizontal=30, vertical=10),
        )
        _zona_contenido.update()

    def _mostrar_bitacora():
        """Inyecta la pantalla de bitácora del turno en la zona intercambiable."""
        from modules.finance.pantalla_bitacora import PantallaBitacora
        _zona_contenido.content = PantallaBitacora(pagina, estado_app)
        _zona_contenido.update()

    def _mostrar_reservaciones():
        """Inyecta la pantalla de reservaciones en la zona intercambiable."""
        from modules.rooms.reservaciones import PantallaReservaciones
        _zona_contenido.content = PantallaReservaciones(
            pagina, estado_app,
            al_actualizar=refrescar_grid_y_tarjetas,
        )
        _zona_contenido.update()

    def _abrir_pendientes():
        """Abre el modal de vueltos y deudas pendientes."""
        from modules.finance.panel_pendientes import abrir_modal_pendientes
        abrir_modal_pendientes(pagina, estado_app)

    def _mostrar_configuracion():
        """Inyecta la pantalla de gestión de caja en la zona intercambiable."""
        from modules.finance.cash_management import PantallaGestionCaja
        _zona_contenido.content = PantallaGestionCaja(pagina, estado_app)
        _zona_contenido.update()

    def refrescar_grid_y_tarjetas():
        """
        Punto de entrada para cualquier operación que modifique el estado de
        las habitaciones. Actualiza tarjetas y grid sin tocar la barra superior.
        Es el reemplazo directo de la antigua refrescar_vista().
        """
        actualizar_tarjetas_resumen()
        if estado_app["vista_activa"] == "dashboard":
            _mostrar_dashboard()

    def cambiar_vista(nombre_vista: str):
        """
        Alterna entre dashboard y configuración.
        Solo modifica el botón de navegación y el contenido de _zona_contenido.
        La barra superior permanece completamente estática.
        """
        estado_app["vista_activa"] = nombre_vista

        # Actualizar texto e ícono del botón sin reconstruir la barra
        if nombre_vista == "configuracion":
            _btn_nav.text = "Dashboard"
            _btn_nav.icon = ft.Icons.DASHBOARD
        else:
            _btn_nav.text = "Configuración"
            _btn_nav.icon = ft.Icons.SETTINGS
        _btn_nav.update()

        # Intercambiar el contenido de forma limpia
        if nombre_vista == "dashboard":
            actualizar_tarjetas_resumen()   # datos frescos al volver
            _mostrar_dashboard()
        elif nombre_vista == "bitacora":
            _mostrar_bitacora()
        elif nombre_vista == "reservaciones":
            _mostrar_reservaciones()
        else:
            _mostrar_configuracion()

    def al_abrir_turno(tasa_final: float):
        """Callback tras la apertura exitosa del turno de caja."""
        estado_app["tasa_cambio"]  = tasa_final
        estado_app["vista_activa"] = "dashboard"
        # Persistir usuario en session para que la bitácora lo lea
        if estado_app.get("usuario_activo"):
            pagina.session.set("usuario_activo", estado_app["usuario_activo"])
        # Primera y única construcción completa del layout de la app
        _construir_interfaz_app()

    def cerrar_sesion():
        """Limpia el estado y regresa a la pantalla de login."""
        estado_app["usuario_activo"] = None
        mostrar_login()

    # ════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN ÚNICA DEL LAYOUT DE LA APP
    # Se ejecuta UNA SOLA VEZ después del login. A partir de aquí todas
    # las actualizaciones son quirúrgicas sobre los contenedores referenciados.
    # ════════════════════════════════════════════════════════════════════════

    def _construir_barra_superior() -> ft.Container:
        """
        Construye la barra superior con referencia al _btn_nav persistente.
        El botón se puede actualizar desde cambiar_vista() sin reconstruir
        esta barra nunca más.
        """
        info_usuario   = estado_app["usuario_activo"]
        nombre_usuario = info_usuario["nombre_completo"] if info_usuario else "Usuario"

        # Configurar estado inicial del botón de navegación
        _btn_nav.text     = "Configuración"
        _btn_nav.icon     = ft.Icons.SETTINGS
        _btn_nav.on_click = lambda _: cambiar_vista(
            "configuracion" if estado_app["vista_activa"] == "dashboard" else "dashboard"
        )

        return ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.HOTEL, size=32, color=ft.Colors.BLUE_700),
                    ft.Text(estado_app["nombre_hotel"], size=22, weight="bold",
                            color=ft.Colors.BLUE_900),
                ]),
                ft.Row([
                    _btn_nav,
                    ft.ElevatedButton(
                        "Bitácora",
                        icon=ft.Icons.HISTORY,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.AMBER_50,
                            color=ft.Colors.AMBER_900,
                            shape=ft.RoundedRectangleBorder(radius=8),
                            side=ft.BorderSide(1, ft.Colors.AMBER_300),
                        ),
                        on_click=lambda _: cambiar_vista("bitacora"),
                    ),
                    ft.ElevatedButton(
                        "Pendientes",
                        icon=ft.Icons.PENDING_ACTIONS,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.RED_50,
                            color=ft.Colors.RED_800,
                            shape=ft.RoundedRectangleBorder(radius=8),
                            side=ft.BorderSide(1, ft.Colors.RED_300),
                        ),
                        on_click=lambda _: _abrir_pendientes(),
                    ),
                    ft.ElevatedButton(
                        "Reservaciones",
                        icon=ft.Icons.EVENT_AVAILABLE,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.GREEN_50,
                            color=ft.Colors.GREEN_800,
                            shape=ft.RoundedRectangleBorder(radius=8),
                            side=ft.BorderSide(1, ft.Colors.GREEN_300),
                        ),
                        on_click=lambda _: cambiar_vista("reservaciones"),
                    ),
                    ft.VerticalDivider(width=20),
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ATTACH_MONEY, size=18, color=ft.Colors.GREEN_700),
                            ft.Text(
                                f"Tasa: Bs. {estado_app['tasa_cambio']:.2f}",
                                size=14, weight="bold",
                            ),
                        ]),
                        padding=ft.padding.all(8),
                        bgcolor=ft.Colors.GREEN_50,
                        border_radius=8,
                    ),
                    ft.VerticalDivider(width=20),
                    ft.Row([
                        ft.Column([
                            ft.Text(nombre_usuario, size=14, weight="bold"),
                            ft.Text(
                                info_usuario["rol"] if info_usuario else "",
                                size=11, color=ft.Colors.GREY_600,
                            ),
                        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
                        ft.CircleAvatar(
                            content=ft.Icon(ft.Icons.PERSON),
                            radius=18, bgcolor=ft.Colors.BLUE_GREY_100,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.LOGOUT_ROUNDED,
                            icon_color=ft.Colors.RED_400,
                            tooltip="Cerrar Sesión",
                            on_click=lambda _: cerrar_sesion(),
                        ),
                    ]),
                ], spacing=15),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=25, vertical=12),
            bgcolor=ft.Colors.WHITE,
            border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.BLACK12)),
        )

    def _construir_interfaz_app():
        """
        Único punto en toda la app que llama a pagina.clean() y pagina.add()
        durante la sesión activa. Tras ejecutarse, el layout no se destruye más.
        """
        pagina.clean()

        # Preparar el contenido inicial del dashboard
        cuadricula = GridHabitaciones(estado_app, al_hacer_clic_habitacion)
        _zona_contenido.content = ft.Container(
            content=cuadricula.construir(),
            expand=True,
            padding=ft.padding.symmetric(horizontal=30, vertical=10),
        )

        # CRÍTICO: pagina.add() debe ir ANTES de cualquier .update() sobre
        # widgets hijos — Flet requiere que el control esté registrado en
        # el árbol de la página antes de poder actualizarlo individualmente.
        pagina.add(ft.Column([
            _construir_barra_superior(),
            _contenedor_tarjetas,
            ft.Container(content=_zona_contenido, expand=True),
        ], expand=True, spacing=0))

        actualizar_tarjetas_resumen()
        pagina.update()

    # ════════════════════════════════════════════════════════════════════════
    # PANTALLA DE LOGIN
    # ════════════════════════════════════════════════════════════════════════

    def mostrar_login():
        """Limpia la pantalla y muestra el formulario de inicio de sesión."""
        pagina.clean()
        pagina.padding   = 0
        pagina.spacing   = 0
        pagina.vertical_alignment   = ft.MainAxisAlignment.START
        pagina.horizontal_alignment = ft.CrossAxisAlignment.START

        pantalla_login = PantallaLogin(pagina, al_iniciar_sesion_exitoso)
        pagina.add(pantalla_login.construir())
        pagina.update()

    def al_iniciar_sesion_exitoso(usuario: dict):
        """
        Callback del login. Guarda el usuario y abre el diálogo de apertura
        de turno. El usuario llega como dict para evitar sesiones ORM detached.
        """
        estado_app["usuario_activo"] = usuario
        DialogoAperturaTurno(pagina, usuario, al_completar=al_abrir_turno).mostrar()

    # ── Punto de entrada de la aplicación ──────────────────────────────────
    mostrar_login()


if __name__ == "__main__":
    ft.app(target=principal)