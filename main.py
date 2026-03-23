import flet as ft
from sqlalchemy import func
from database.connection import inicializar_bd, SesionLocal
from database.models import Habitacion, EstadoHabitacion, Estadia, Huesped, Turno
from modules.auth.login import PantallaLogin
from modules.rooms.management import GridHabitaciones
from modules.rooms.details import DialogoDetallesHabitacion
from utils.helpers import cargar_configuracion_bd
from modules.finance.cash_opening import DialogoAperturaTurno


def configurar_tema(pagina: ft.Page):
    """Tema moderno con Material 3."""
    pagina.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ft.Colors.BLUE_700,
            secondary=ft.Colors.CYAN_700,
            surface=ft.Colors.WHITE,
            background=ft.Colors.GREY_50,
        ),
        font_family="Roboto",
        use_material3=True,
    )
    pagina.dark_theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ft.Colors.BLUE_300,
            secondary=ft.Colors.CYAN_300,
            surface=ft.Colors.GREY_900,
            background=ft.Colors.BLACK,
        ),
        use_material3=True,
    )


def principal(pagina: ft.Page):
    """
    Versión basada en tu código original que funciona.
    Se añade tema moderno y se mejoran las tarjetas del resumen,
    ajustando el tamaño del contenedor para que quepan correctamente.
    """
    # ── Configuración de la ventana ─────────────────────────────────────────
    pagina.title = "Hotel Management System"
    pagina.theme_mode = ft.ThemeMode.LIGHT
    pagina.padding = 0
    pagina.spacing = 0
    pagina.window.width = 1400
    pagina.window.height = 900
    pagina.window.min_width = 1200
    pagina.window.min_height = 700

    # Aplicar tema
    configurar_tema(pagina)

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
        "tasa_cambio": float(config_inicial.get("exchange_rate", 35.5)),
        "nombre_hotel": config_inicial.get("hotel_name", "Mi Hotel"),
        "habitacion_sel": None,
        "vista_activa": "dashboard",
        "resumen_visible": False
    }

    # ════════════════════════════════════════════════════════════════════════
    # REFERENCIAS A WIDGETS PERSISTENTES
    # ════════════════════════════════════════════════════════════════════════

    _zona_contenido = ft.Container(expand=True)
    _fila_tarjetas = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=15)
    _contenedor_resumen_animado = ft.Container(
        content=_fila_tarjetas,
        padding=ft.padding.only(bottom=20, left=20, right=20),
        height=0,
        opacity=0,
        animate=ft.Animation(400, ft.AnimationCurve.DECELERATE),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    _btn_toggle_resumen = ft.TextButton(
        "Mostrar Resumen",
        icon=ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED,
        style=ft.ButtonStyle(color=ft.Colors.OUTLINE),
        on_click=lambda e: toggle_resumen(e)
    )

    # ════════════════════════════════════════════════════════════════════════
    # LÓGICA DE INTERFAZ Y NEGOCIO
    # ════════════════════════════════════════════════════════════════════════

    def toggle_theme(e):
        if pagina.theme_mode == ft.ThemeMode.LIGHT:
            pagina.theme_mode = ft.ThemeMode.DARK
            e.control.icon = ft.Icons.LIGHT_MODE
            e.control.tooltip = "Activar Modo Claro"
        else:
            pagina.theme_mode = ft.ThemeMode.LIGHT
            e.control.icon = ft.Icons.DARK_MODE
            e.control.tooltip = "Activar Modo Oscuro"
        pagina.update()

    def toggle_resumen(e):
        estado_app["resumen_visible"] = not estado_app["resumen_visible"]
        if estado_app["resumen_visible"]:
            actualizar_tarjetas_resumen()
            _contenedor_resumen_animado.height = 140   # Aumentado para que quepan los iconos
            _contenedor_resumen_animado.opacity = 1
            _btn_toggle_resumen.text = "Ocultar Resumen"
            _btn_toggle_resumen.icon = ft.Icons.KEYBOARD_ARROW_UP_ROUNDED
        else:
            _contenedor_resumen_animado.height = 0
            _contenedor_resumen_animado.opacity = 0
            _btn_toggle_resumen.text = "Mostrar Resumen"
            _btn_toggle_resumen.icon = ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED
        _contenedor_resumen_animado.update()
        _btn_toggle_resumen.update()

    def obtener_estadisticas_habitaciones() -> dict:
        sesion = SesionLocal()
        try:
            resultados = (
                sesion.query(Habitacion.estado, func.count(Habitacion.id))
                .group_by(Habitacion.estado).all()
            )
            conteos = {estado: cantidad for estado, cantidad in resultados}
            return {
                "total": sum(conteos.values()),
                "libres": conteos.get(EstadoHabitacion.FREE, 0),
                "ocupadas": conteos.get(EstadoHabitacion.OCCUPIED, 0),
                "limpieza": conteos.get(EstadoHabitacion.CLEANING, 0),
                "mantenimiento": conteos.get(EstadoHabitacion.MAINTENANCE, 0),
            }
        except:
            return {k: 0 for k in ["total", "libres", "ocupadas", "limpieza", "mantenimiento"]}
        finally:
            sesion.close()

    def al_hacer_clic_habitacion(habitacion):
        if habitacion.estado == EstadoHabitacion.FREE:
            from modules.rooms.checkin import DialogoCheckIn
            DialogoCheckIn(pagina, habitacion, al_completar=refrescar_grid_y_tarjetas).mostrar()
        elif habitacion.estado == EstadoHabitacion.CLEANING:
            _mostrar_dialogo_limpieza(habitacion)
        elif habitacion.estado == EstadoHabitacion.OCCUPIED:
            DialogoDetallesHabitacion(
                pagina, habitacion,
                al_solicitar_checkout=iniciar_checkout,
                al_actualizar_grid=refrescar_grid_y_tarjetas,
            ).mostrar()

    def _mostrar_dialogo_limpieza(habitacion):
        def marcar_libre(_):
            pagina.close(dlg)
            sesion = SesionLocal()
            try:
                hab_bd = sesion.get(Habitacion, habitacion.id)
                hab_bd.estado = EstadoHabitacion.FREE
                sesion.commit()
                refrescar_grid_y_tarjetas()
                pagina.open(ft.SnackBar(ft.Text(f"Hab. {habitacion.numero} lista"), bgcolor=ft.Colors.GREEN_700))
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Limpieza - Hab. {habitacion.numero}"),
            content=ft.Text("¿Marcar como disponible?"),
            actions=[
                ft.TextButton("No", on_click=lambda _: pagina.close(dlg)),
                ft.ElevatedButton("Sí, lista", on_click=marcar_libre, bgcolor=ft.Colors.GREEN_700, color="white")
            ]
        )
        pagina.open(dlg)

    def iniciar_checkout(habitacion):
        from modules.rooms.checkout import CheckOutWizard
        CheckOutWizard(pagina, habitacion, al_completar=lambda _: refrescar_grid_y_tarjetas()).mostrar()

    # Tarjetas mejoradas con iconos (ajustadas para que no sobresalgan)
    def _construir_tarjeta(etiqueta, valor, color, icono, subtexto):
        return ft.Card(
            elevation=2,
            shape=ft.RoundedRectangleBorder(radius=12),
            content=ft.Container(
                content=ft.Column([
                    ft.Icon(icono, size=24, color=color),   # Icono un poco más pequeño
                    ft.Text(etiqueta, size=11, weight="bold", color=ft.Colors.OUTLINE),
                    ft.Text(str(valor), size=26, weight="bold", color=color),
                    ft.Text(subtexto, size=9, color=ft.Colors.OUTLINE),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                padding=ft.padding.symmetric(vertical=8, horizontal=6),
                width=120,   # Ancho reducido
            )
        )

    def actualizar_tarjetas_resumen():
        stats = obtener_estadisticas_habitaciones()
        _fila_tarjetas.controls = [
            _construir_tarjeta("TOTAL", stats["total"], ft.Colors.ON_SURFACE, ft.Icons.HOTEL, "Habitaciones"),
            _construir_tarjeta("LIBRES", stats["libres"], ft.Colors.GREEN_600, ft.Icons.BED, "Disponibles"),
            _construir_tarjeta("OCUPADAS", stats["ocupadas"], ft.Colors.RED_600, ft.Icons.PERSON, "Huéspedes"),
            _construir_tarjeta("LIMPIEZA", stats["limpieza"], ft.Colors.CYAN_700, ft.Icons.CLEANING_SERVICES, "En aseo"),
            _construir_tarjeta("MTTO.", stats["mantenimiento"], ft.Colors.PURPLE_600, ft.Icons.BUILD, "Inactivas"),
        ]
        if _fila_tarjetas.page:
            _fila_tarjetas.update()

    def refrescar_grid_y_tarjetas():
        if estado_app["resumen_visible"]:
            actualizar_tarjetas_resumen()
        if estado_app["vista_activa"] == "dashboard":
            _mostrar_dashboard()

    def _mostrar_dashboard():
        try:
            cuadricula = GridHabitaciones(estado_app, al_hacer_clic_habitacion)
            _zona_contenido.content = ft.Container(
                content=cuadricula.construir(), expand=True,
                padding=ft.padding.symmetric(horizontal=30, vertical=10)
            )
            _zona_contenido.update()
        except Exception as e:
            print(f"Error en _mostrar_dashboard: {e}")
            _zona_contenido.content = ft.Text(f"Error: {e}", color="red")
            _zona_contenido.update()

    def cambiar_vista(nombre_vista: str):
        estado_app["vista_activa"] = nombre_vista
        if nombre_vista == "configuracion":
            from modules.finance.cash_management import PantallaGestionCaja
            _zona_contenido.content = PantallaGestionCaja(pagina, estado_app)
        elif nombre_vista == "bitacora":
            from modules.finance.pantalla_bitacora import PantallaBitacora
            _zona_contenido.content = PantallaBitacora(pagina, estado_app)
        elif nombre_vista == "reservaciones":
            from modules.rooms.reservaciones import PantallaReservaciones
            _zona_contenido.content = PantallaReservaciones(pagina, estado_app, al_actualizar=refrescar_grid_y_tarjetas)
        else:
            _mostrar_dashboard()
        _zona_contenido.update()

    def cerrar_sesion():
        sesion = SesionLocal()
        try:
            turno_activo = sesion.query(Turno).filter(Turno.activo == True).first()
            id_turno = turno_activo.id if turno_activo else None
        finally:
            sesion.close()

        if id_turno:
            from modules.finance.shift_closing import DialogoCierreTurno
            DialogoCierreTurno(pagina=pagina, id_turno=id_turno, al_cerrar_turno=_ejecutar_cierre_sesion).mostrar()
        else:
            _ejecutar_cierre_sesion()

    def _ejecutar_cierre_sesion():
        estado_app["usuario_activo"] = None
        mostrar_login()

    # BARRA SUPERIOR IDÉNTICA A TU ORIGINAL (sin cambios)
    def _construir_barra_superior() -> ft.Container:
        info_usuario = estado_app["usuario_activo"]
        nombre_user = info_usuario["nombre_completo"] if info_usuario else "Usuario"

        _btn_inicio = ft.ElevatedButton("Inicio", icon=ft.Icons.HOME, on_click=lambda _: cambiar_vista("dashboard"))
        _btn_config = ft.ElevatedButton("Configuración", icon=ft.Icons.SETTINGS, on_click=lambda _: cambiar_vista("configuracion"))

        return ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.HOTEL, size=32, color=ft.Colors.BLUE_700),
                    ft.Text(estado_app["nombre_hotel"], size=22, weight="bold", color=ft.Colors.BLUE_700),
                ]),
                ft.Row([
                    _btn_inicio,
                    _btn_config,
                    ft.ElevatedButton("Bitácora", icon=ft.Icons.HISTORY, on_click=lambda _: cambiar_vista("bitacora")),
                    ft.ElevatedButton("Pendientes", icon=ft.Icons.PENDING_ACTIONS, on_click=lambda _: _abrir_pendientes()),
                    ft.ElevatedButton("Reservas", icon=ft.Icons.EVENT_AVAILABLE, on_click=lambda _: cambiar_vista("reservaciones")),
                    ft.VerticalDivider(width=10),
                    ft.Text(f"Tasa: Bs. {estado_app['tasa_cambio']:.2f}", weight="bold"),
                    ft.VerticalDivider(width=10),
                    ft.Column([ft.Text(nombre_user, size=13, weight="bold"), ft.Text(info_usuario["rol"] if info_usuario else "", size=10)], spacing=0),
                    ft.IconButton(icon=ft.Icons.DARK_MODE, tooltip="Activar Modo Oscuro", on_click=toggle_theme),
                    ft.IconButton(ft.Icons.LOGOUT_ROUNDED, icon_color=ft.Colors.RED_400, on_click=lambda _: cerrar_sesion()),
                ], spacing=10),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=20, vertical=10),
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.OUTLINE_VARIANT))
        )

    def _abrir_pendientes():
        from modules.finance.panel_pendientes import abrir_modal_pendientes
        abrir_modal_pendientes(pagina, estado_app)

    def _construir_interfaz_app():
        pagina.clean()
        pagina.add(ft.Column([
            _construir_barra_superior(),
            ft.Container(content=_btn_toggle_resumen, alignment=ft.alignment.center, padding=5),
            _contenedor_resumen_animado,
            ft.Container(content=_zona_contenido, expand=True),
        ], expand=True, spacing=0))
        _mostrar_dashboard()

    def mostrar_login():
        pagina.clean()
        pagina.add(PantallaLogin(pagina, al_iniciar_sesion_exitoso).construir())

    def al_iniciar_sesion_exitoso(usuario):
        estado_app["usuario_activo"] = usuario
        DialogoAperturaTurno(pagina, usuario, al_completar=al_abrir_turno).mostrar()

    def al_abrir_turno(tasa):
        estado_app["tasa_cambio"] = tasa
        _construir_interfaz_app()

    mostrar_login()


if __name__ == "__main__":
    ft.app(target=principal)