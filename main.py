# main.py

import flet as ft
from sqlalchemy import func
from database.connection import inicializar_bd, SesionLocal
from database.models import Habitacion, EstadoHabitacion
from modules.auth.login import PantallaLogin
from modules.rooms.management import GridHabitaciones
from modules.rooms.details import DialogoDetallesHabitacion
from utils.helpers import cargar_configuracion_bd
from modules.finance.cash_opening import DialogoAperturaTurno


def principal(pagina: ft.Page):
    """
    Función principal de la aplicación.
    Configura la página, inicializa la BD y lanza la pantalla de login.
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
    # Diccionario mutable compartido entre todos los módulos.
    estado_app = {
        "usuario_activo": None,
        "tasa_cambio":    float(config_inicial.get("exchange_rate", 35.5)),
        "nombre_hotel":   config_inicial.get("hotel_name", "Mi Hotel"),
        "habitacion_sel": None,
        "vista_activa":   "dashboard",  # 'dashboard' o 'configuracion'
    }

    # ════════════════════════════════════════════════════════════════════════
    # LÓGICA DE NEGOCIO
    # ════════════════════════════════════════════════════════════════════════

    def obtener_estadisticas_habitaciones() -> dict:
        """
        Devuelve el conteo de habitaciones por estado en una sola consulta agrupada.
        Eficiente porque usa GROUP BY en lugar de consultas individuales.
        """
        sesion = SesionLocal()
        try:
            resultados = (
                sesion.query(Habitacion.estado, func.count(Habitacion.id))
                .group_by(Habitacion.estado)
                .all()
            )
            conteos = {estado: cantidad for estado, cantidad in resultados}
            return {
                "total":        sum(conteos.values()),
                "libres":       conteos.get(EstadoHabitacion.FREE,        0),
                "ocupadas":     conteos.get(EstadoHabitacion.OCCUPIED,    0),
                "reservadas":   conteos.get(EstadoHabitacion.RESERVED,    0),
                "limpieza":     conteos.get(EstadoHabitacion.CLEANING,    0),
                "mantenimiento":conteos.get(EstadoHabitacion.MAINTENANCE, 0),
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
            dialogo_checkin = DialogoCheckIn(pagina, habitacion, al_completar=refrescar_vista)
            dialogo_checkin.mostrar()

        elif habitacion.estado == EstadoHabitacion.OCCUPIED:
            detalles = DialogoDetallesHabitacion(
                pagina, habitacion,
                al_solicitar_checkout=iniciar_checkout,
            )
            detalles.mostrar()

    def iniciar_checkout(habitacion):
        """Inicia el proceso de check-out (flujo a completar)."""
        pagina.open(ft.SnackBar(
            ft.Text(f"Iniciando proceso de salida para Hab {habitacion.numero}...")
        ))

    # ════════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN Y RENDERIZADO
    # ════════════════════════════════════════════════════════════════════════

    def refrescar_vista():
        """Recarga el contenido de la vista activa."""
        renderizar_contenido_app()

    def cambiar_vista(nombre_vista: str):
        """Alterna entre el dashboard y la vista de configuración."""
        estado_app["vista_activa"] = nombre_vista
        renderizar_contenido_app()

    def al_abrir_turno(tasa_final: float):
        """Callback tras la apertura exitosa del turno de caja."""
        estado_app["tasa_cambio"]  = tasa_final
        estado_app["vista_activa"] = "dashboard"
        renderizar_contenido_app()
        print("Sesión iniciada y Dashboard cargado")

    def cerrar_sesion():
        """Limpia el estado y regresa a la pantalla de login."""
        estado_app["usuario_activo"] = None
        mostrar_login()

    # ════════════════════════════════════════════════════════════════════════
    # COMPONENTES DE INTERFAZ
    # ════════════════════════════════════════════════════════════════════════

    def crear_tarjetas_resumen():
        """Crea las tarjetas informativas superiores con los conteos de habitaciones."""
        estadisticas = obtener_estadisticas_habitaciones()

        def construir_tarjeta(etiqueta, valor, color, subtexto):
            return ft.Card(content=ft.Container(
                content=ft.Column([
                    ft.Text(etiqueta, size=12, color=ft.Colors.GREY_700),
                    ft.Text(str(valor), size=28, weight=ft.FontWeight.BOLD, color=color),
                    ft.Text(subtexto, size=10, color=ft.Colors.GREY_600),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                padding=10, width=140,
            ))

        return ft.Container(
            content=ft.Row([
                construir_tarjeta("Total",         estadisticas["total"],        ft.Colors.BLACK,  "habitaciones"),
                construir_tarjeta("Libres",        estadisticas["libres"],       ft.Colors.GREEN,  "disponibles"),
                construir_tarjeta("Ocupadas",      estadisticas["ocupadas"],     ft.Colors.RED,    "con huéspedes"),
                construir_tarjeta("Limpieza",      estadisticas["limpieza"],     ft.Colors.BLUE,   "en aseo"),
                construir_tarjeta("Mantenimiento", estadisticas["mantenimiento"],ft.Colors.PURPLE, "fuera de servicio"),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=15),
            padding=20,
        )

    def crear_barra_superior():
        """Crea la barra de navegación superior con el nombre del hotel, tasa y usuario."""
        info_usuario  = estado_app["usuario_activo"]
        nombre_usuario = info_usuario["nombre_completo"] if info_usuario else "Usuario"
        vista_actual   = estado_app["vista_activa"]

        return ft.Container(
            content=ft.Row([
                # Logo y nombre del hotel
                ft.Row([
                    ft.Icon(ft.Icons.HOTEL, size=32, color=ft.Colors.BLUE_700),
                    ft.Text(estado_app["nombre_hotel"], size=22, weight="bold",
                            color=ft.Colors.BLUE_900),
                ]),
                # Acciones y perfil
                ft.Row([
                    ft.ElevatedButton(
                        text="Dashboard" if vista_actual == "configuracion" else "Configuración",
                        icon=(
                            ft.Icons.DASHBOARD if vista_actual == "configuracion"
                            else ft.Icons.SETTINGS
                        ),
                        on_click=lambda _: cambiar_vista(
                            "dashboard" if vista_actual == "configuracion" else "configuracion"
                        ),
                        style=ft.ButtonStyle(
                            color=ft.Colors.BLUE_700, bgcolor=ft.Colors.BLUE_50,
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                    ),
                    ft.VerticalDivider(width=20),
                    # Indicador de la tasa de cambio vigente
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ATTACH_MONEY, size=18, color=ft.Colors.GREEN_700),
                            ft.Text(
                                f"Tasa: Bs. {estado_app['tasa_cambio']:.2f}",
                                size=14, weight="bold",
                            ),
                        ]),
                        padding=ft.padding.all(8),
                        bgcolor=ft.Colors.GREEN_50, border_radius=8,
                    ),
                    ft.VerticalDivider(width=20),
                    # Perfil del usuario activo
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

    def renderizar_contenido_app():
        """Función central que dibuja la interfaz principal o la vista de configuración."""
        pagina.clean()
        encabezado = crear_barra_superior()

        if estado_app["vista_activa"] == "dashboard":
            cuadricula = GridHabitaciones(estado_app, al_hacer_clic_habitacion)
            contenido  = ft.Column([
                crear_tarjetas_resumen(),
                ft.Container(
                    content=cuadricula.construir(),
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=30, vertical=10),
                ),
            ], expand=True, spacing=0)
        else:
            from modules.finance.cash_management import PantallaGestionCaja
            contenido = PantallaGestionCaja(pagina, estado_app)

        pagina.add(ft.Column([
            encabezado,
            ft.Container(content=contenido, expand=True),
        ], expand=True, spacing=0))
        pagina.update()

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
        Callback del login: guarda el usuario y lanza la apertura de turno.
        El usuario es un dict (no un objeto ORM) para evitar problemas de sesión detached.
        """
        estado_app["usuario_activo"] = usuario
        dialogo_apertura = DialogoAperturaTurno(
            pagina, usuario, al_completar=al_abrir_turno,
        )
        dialogo_apertura.mostrar()

    # ── Punto de entrada de la aplicación ──────────────────────────────────
    mostrar_login()


if __name__ == "__main__":
    ft.app(target=principal)