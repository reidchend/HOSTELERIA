import flet as ft
from sqlalchemy import func
from database.connection import inicializar_bd, SesionLocal
from database.models import Habitacion, EstadoHabitacion, Estadia, Huesped, Turno
from modules.auth.login import PantallaLogin
from modules.rooms.management import GridHabitaciones
from modules.rooms.details import DialogoDetallesHabitacion
from utils.helpers import cargar_configuracion_bd
from modules.finance.cash_opening import DialogoAperturaTurno

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE TEMAS NATIVOS (Compatible con Flet 0.28.3)
# ══════════════════════════════════════════════════════════════════════════════

COLOR_ACCENT = "#0EA5E9"  # Azul Primario
COLOR_ACCENT_DARK = "#38BDF8"

TEMA_CLARO = ft.Theme(
    color_scheme=ft.ColorScheme(
        primary=COLOR_ACCENT,
        surface="#FFFFFF",
        on_surface="#0F172A",     # Texto principal
        on_surface_variant="#64748B", # Texto secundario
        background="#F1F5F9",
        outline="#E2E8F0",        # Bordes
        primary_container="#DBEAFE", # Fondo de elementos destacados
        on_primary_container="#1E40AF",
    ),
    visual_density=ft.VisualDensity.COMFORTABLE,
)

TEMA_OSCURO = ft.Theme(
    color_scheme=ft.ColorScheme(
        primary=COLOR_ACCENT_DARK,
        surface="#0D1421",
        on_surface="#E2E8F0",
        on_surface_variant="#94A3B8",
        background="#070C14",
        outline="#1A2535",
        primary_container="#1E3A5F", # Contenedores oscuros
        on_primary_container="#E0F2FE",
    ),
    visual_density=ft.VisualDensity.COMFORTABLE,
)

# Dimensiones del Sidebar
_W_EXPANDED = 220
_W_COLLAPSED = 70

# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def principal(pagina: ft.Page):
    pagina.title = "La Posada de Daniel C.A. - PMS"
    
    # Configuración de Temas Nativa
    pagina.theme = TEMA_CLARO
    pagina.dark_theme = TEMA_OSCURO
    pagina.theme_mode = ft.ThemeMode.LIGHT
    
    pagina.padding = 0
    pagina.spacing = 0
    pagina.window.width = 1400
    pagina.window.height = 900
    pagina.window.min_width = 1100
    pagina.window.min_height = 700
    
    pagina.bgcolor = None 

    # Inicialización de Base de Datos
    inicializar_bd()

    # Carga de configuración inicial desde BD
    sesion_inicio = SesionLocal()
    try:
        config_inicial = cargar_configuracion_bd(sesion_inicio)
    except Exception:
        config_inicial = {}
    finally:
        sesion_inicio.close()

    # Estado global de la aplicación
    estado_app = {
        "usuario_activo": None,
        "tasa_cambio": float(config_inicial.get("exchange_rate", 35.5)),
        "nombre_hotel": config_inicial.get("hotel_name", "La Posada"),
        "vista_activa": "dashboard",
    }

    # Zona de contenido dinámico con animación de opacidad
    _zona_contenido = ft.Container(
        expand=True, 
        animate_opacity=300,
        content=ft.ProgressRing(visible=False)
    )
    _sidebar_ref = [None]

    # ════════════════════════════════════════════════════════════════════════
    # LÓGICA DE TEMAS Y NAVEGACIÓN
    # ════════════════════════════════════════════════════════════════════════

    def toggle_theme(e):
        if pagina.theme_mode == ft.ThemeMode.LIGHT:
            pagina.theme_mode = ft.ThemeMode.DARK
            e.control.icon = ft.Icons.LIGHT_MODE
        else:
            pagina.theme_mode = ft.ThemeMode.LIGHT
            e.control.icon = ft.Icons.DARK_MODE
        pagina.update()

    def cambiar_vista(nombre_vista: str):
        if estado_app["vista_activa"] == nombre_vista:
            return
            
        estado_app["vista_activa"] = nombre_vista
        if _sidebar_ref[0]:
            _sidebar_ref[0].actualizar_activo(nombre_vista)

        _zona_contenido.opacity = 0
        _zona_contenido.update()

        if nombre_vista == "configuracion":
            from modules.finance.cash_management import PantallaGestionCaja
            _zona_contenido.content = PantallaGestionCaja(pagina, estado_app)
        elif nombre_vista == "bitacora":
            from modules.finance.pantalla_bitacora import PantallaBitacora
            _zona_contenido.content = PantallaBitacora(pagina, estado_app)
        elif nombre_vista == "reservaciones":
            from modules.rooms.reservaciones import PantallaReservaciones
            _zona_contenido.content = PantallaReservaciones(pagina, estado_app, al_actualizar=refrescar_grid)
        elif nombre_vista == "pendientes":
            from modules.finance.panel_pendientes import abrir_modal_pendientes
            abrir_modal_pendientes(pagina, estado_app)
            _zona_contenido.opacity = 1
            _zona_contenido.update()
            return
        else:
            _mostrar_dashboard()
            _zona_contenido.opacity = 1
            _zona_contenido.update()
            return

        _zona_contenido.opacity = 1
        _zona_contenido.update()

    def refrescar_grid():
        if estado_app["vista_activa"] == "dashboard":
            _mostrar_dashboard()

    def _mostrar_dashboard():
        cuadricula = GridHabitaciones(estado_app, al_hacer_clic_habitacion)
        _zona_contenido.content = ft.Container(
            content=cuadricula.construir(),
            expand=True,
            padding=20
        )
        _zona_contenido.update()

    def al_hacer_clic_habitacion(habitacion):
        if habitacion.estado == EstadoHabitacion.FREE:
            from modules.rooms.checkin import DialogoCheckIn
            DialogoCheckIn(pagina, habitacion, al_completar=refrescar_grid).mostrar()
        elif habitacion.estado == EstadoHabitacion.CLEANING:
            _mostrar_dialogo_limpieza(habitacion)
        elif habitacion.estado == EstadoHabitacion.OCCUPIED:
            DialogoDetallesHabitacion(
                pagina, 
                habitacion, 
                al_solicitar_checkout=iniciar_checkout, 
                al_actualizar_grid=refrescar_grid
            ).mostrar()

    def _mostrar_dialogo_limpieza(habitacion):
        def marcar_libre(_):
            pagina.close(dlg)
            sesion = SesionLocal()
            try:
                hab_bd = sesion.get(Habitacion, habitacion.id)
                hab_bd.estado = EstadoHabitacion.FREE
                sesion.commit()
                refrescar_grid()
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Limpieza — Hab. {habitacion.numero}"),
            content=ft.Text("¿Confirmar que la habitación está lista para recibir huéspedes?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: pagina.close(dlg)),
                ft.ElevatedButton("Sí, disponible", on_click=marcar_libre, bgcolor=ft.Colors.GREEN_700, color="white"),
            ],
        )
        pagina.open(dlg)

    def iniciar_checkout(habitacion):
        from modules.rooms.checkout import CheckOutWizard
        CheckOutWizard(pagina, habitacion, al_completar=lambda _: refrescar_grid()).mostrar()

    # ════════════════════════════════════════════════════════════════════════
    # COMPONENTES DE ESTRUCTURA
    # ════════════════════════════════════════════════════════════════════════

    class Sidebar(ft.Container):
        def __init__(self):
            super().__init__()
            self._activo = "dashboard"
            self._items_refs = {}
            self._expandido = False
            self._construir()

        def _construir(self):
            self.width = _W_EXPANDED if self._expandido else _W_COLLAPSED
            self.bgcolor = ft.Colors.SURFACE
            self.border = ft.border.only(right=ft.border.BorderSide(1, ft.Colors.OUTLINE))
            
            # AJUSTE DE LA ANIMACIÓN:
            # - duration: milisegundos que dura la transición
            # - curve: el ritmo de la animación (DECELERATE, EASE, BOUNCE, etc.)
            self.animate_size = ft.Animation(
                duration=450, 
                curve=ft.AnimationCurve.EASE_OUT_QUINT
            )

            # Referencia al botón toggle
            self._btn_toggle = ft.IconButton(
                icon=ft.Icons.CHEVRON_RIGHT_ROUNDED if not self._expandido else ft.Icons.CHEVRON_LEFT_ROUNDED,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                on_click=self._toggle_colapso,
                width=40,
            )

            # Logo
            self._logo_badge = ft.Container(
                content=ft.Text("LP", weight="bold", color="white"),
                width=36, height=36, bgcolor=ft.Colors.PRIMARY, border_radius=10, alignment=ft.alignment.center
            )
            
            self._logo_texto = ft.Container(
                content=ft.Column([
                    ft.Text("La Posada", size=14, weight="bold", color=ft.Colors.ON_SURFACE, no_wrap=True),
                    ft.Text("de Daniel C.A.", size=10, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
                ], spacing=0),
                visible=self._expandido,
                animate_opacity=300
            )

            # Contenedor del header para acceso fácil
            self._header_container = ft.Container(
                content=ft.Row([
                    ft.Row([self._logo_badge, self._logo_texto], spacing=10, tight=True, visible=self._expandido),
                    self._btn_toggle
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN if self._expandido else ft.MainAxisAlignment.CENTER),
                padding=ft.padding.only(left=12 if self._expandido else 0, right=4 if self._expandido else 0, top=20, bottom=20),
                border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.OUTLINE))
            )

            # Items de Navegación
            nav_items = [
                ("dashboard", "Inicio", ft.Icons.GRID_VIEW_ROUNDED),
                ("reservaciones", "Reservas", ft.Icons.EVENT_AVAILABLE_ROUNDED),
                ("pendientes", "Pendientes", ft.Icons.PENDING_ACTIONS_ROUNDED),
                ("bitacora", "Bitácora", ft.Icons.HISTORY_ROUNDED),
                ("configuracion", "Configuración", ft.Icons.SETTINGS_ROUNDED),
            ]

            info_user = estado_app.get("usuario_activo") or {}
            nombre = info_user.get("nombre_completo", "Usuario")
            
            self._user_info_labels = ft.Container(
                content=ft.Column([
                    ft.Text(nombre, size=12, weight="bold", color=ft.Colors.ON_SURFACE, overflow="ellipsis", no_wrap=True),
                    ft.Text(info_user.get("rol", "Personal"), size=10, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
                ], spacing=0, expand=True),
                visible=self._expandido,
                animate_opacity=300,
                expand=True
            )

            # Referencia al botón logout
            self._btn_logout = ft.IconButton(
                ft.Icons.LOGOUT_ROUNDED, 
                icon_size=18, 
                on_click=lambda _: cerrar_sesion(), 
                visible=self._expandido
            )

            self._footer_container = ft.Container(
                content=ft.Row([
                    ft.Container(
                        width=32, height=32, bgcolor=ft.Colors.PRIMARY_CONTAINER, 
                        border_radius=8, alignment=ft.alignment.center,
                        content=ft.Text(nombre[0].upper() if nombre else "U", size=12, weight="bold", color=ft.Colors.ON_PRIMARY_CONTAINER)
                    ),
                    self._user_info_labels,
                    self._btn_logout
                ], alignment=ft.MainAxisAlignment.CENTER if not self._expandido else ft.MainAxisAlignment.START),
                padding=ft.padding.symmetric(horizontal=12 if self._expandido else 0, vertical=15)
            )

            self.content = ft.Column([
                self._header_container,
                ft.Container(height=10),
                ft.Column([self._nav_item(v, l, i) for v, l, i in nav_items], spacing=4, expand=True),
                ft.Divider(height=1, color=ft.Colors.OUTLINE),
                self._footer_container
            ], spacing=0)

        def _nav_item(self, vista, label, icono):
            es_activo = self._activo == vista
            item = ft.Container(
                content=ft.Row([
                    ft.Icon(icono, size=20, color=ft.Colors.PRIMARY if es_activo else ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(
                        label, size=13, weight="w600" if es_activo else "w400", 
                        color=ft.Colors.ON_SURFACE if es_activo else ft.Colors.ON_SURFACE_VARIANT,
                        visible=self._expandido,
                        no_wrap=True
                    )
                ], spacing=12 if self._expandido else 0, alignment=ft.MainAxisAlignment.CENTER if not self._expandido else ft.MainAxisAlignment.START),
                padding=ft.padding.symmetric(horizontal=12 if self._expandido else 0, vertical=10),
                margin=ft.margin.symmetric(horizontal=8 if self._expandido else 4),
                border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY) if es_activo else None,
                on_click=lambda _: cambiar_vista(vista),
                tooltip=label if not self._expandido else None
            )
            self._items_refs[vista] = item
            return item

        def _toggle_colapso(self, _):
            self._expandido = not self._expandido
            self.width = _W_EXPANDED if self._expandido else _W_COLLAPSED
            
            # Cambiar icono
            self._btn_toggle.icon = ft.Icons.CHEVRON_LEFT_ROUNDED if self._expandido else ft.Icons.CHEVRON_RIGHT_ROUNDED
            
            # Visibilidad de elementos de texto
            self._logo_texto.visible = self._expandido
            self._user_info_labels.visible = self._expandido
            self._btn_logout.visible = self._expandido 
            
            # Ajustar items
            for item in self._items_refs.values():
                item.content.controls[1].visible = self._expandido
                item.content.spacing = 12 if self._expandido else 0
                item.padding = ft.padding.symmetric(horizontal=12 if self._expandido else 0, vertical=10)
                item.margin = ft.margin.symmetric(horizontal=8 if self._expandido else 4)
                item.content.alignment = ft.MainAxisAlignment.START if self._expandido else ft.MainAxisAlignment.CENTER

            # Ajustar Header
            self._header_container.content.alignment = ft.MainAxisAlignment.SPACE_BETWEEN if self._expandido else ft.MainAxisAlignment.CENTER
            self._header_container.padding = ft.padding.only(left=12 if self._expandido else 0, right=4 if self._expandido else 0, top=20, bottom=20)
            self._header_container.content.controls[0].visible = self._expandido
            
            # Ajustar Footer
            self._footer_container.content.alignment = ft.MainAxisAlignment.START if self._expandido else ft.MainAxisAlignment.CENTER
            self._footer_container.padding = ft.padding.symmetric(horizontal=12 if self._expandido else 0, vertical=15)
            
            self.update()

        def actualizar_activo(self, vista):
            self._activo = vista
            self._construir()
            self.update()

    def _construir_topbar():
        tasa = estado_app.get("tasa_cambio", 35.5)
        nombre_u = estado_app["usuario_activo"].get("nombre_completo", "Admin") if estado_app["usuario_activo"] else "User"
        
        return ft.Container(
            content=ft.Row([
                ft.Text(estado_app["nombre_hotel"], weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=ft.Colors.OUTLINE),
                ft.Text("Recepción", size=14, weight="w600"),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CURRENCY_EXCHANGE, size=14, color=ft.Colors.PRIMARY),
                        ft.Text(f"Tasa: {tasa:,.2f} Bs.", size=12, weight="bold", color=ft.Colors.PRIMARY)
                    ], spacing=5),
                    bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY),
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    border_radius=20
                ),
                ft.IconButton(
                    icon=ft.Icons.LIGHT_MODE if pagina.theme_mode == ft.ThemeMode.DARK else ft.Icons.DARK_MODE,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    on_click=toggle_theme
                ),
                ft.VerticalDivider(width=1, color=ft.Colors.OUTLINE),
                ft.Text(nombre_u, size=12, weight="bold")
            ], spacing=15),
            padding=ft.padding.symmetric(horizontal=20),
            height=60,
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.OUTLINE))
        )

    def _construir_interfaz_app():
        pagina.clean()
        pagina.bgcolor = None
        sidebar = Sidebar()
        _sidebar_ref[0] = sidebar
        
        layout = ft.Row([
            sidebar,
            ft.Column([
                _construir_topbar(),
                ft.Container(content=_zona_contenido, expand=True, bgcolor=None) 
            ], expand=True, spacing=0)
        ], expand=True, spacing=0)
        
        pagina.add(layout)
        _mostrar_dashboard()

    def al_iniciar_sesion_exitoso(usuario):
        estado_app["usuario_activo"] = usuario
        DialogoAperturaTurno(pagina, usuario, al_completar=al_abrir_turno).mostrar()

    def al_abrir_turno(tasa):
        estado_app["tasa_cambio"] = tasa
        _construir_interfaz_app()

    def cerrar_sesion():
        estado_app["usuario_activo"] = None
        mostrar_login()

    def mostrar_login():
        pagina.clean()
        pagina.bgcolor = "#070C14" 
        pagina.add(PantallaLogin(pagina, al_iniciar_sesion_exitoso).construir())

    mostrar_login()

if __name__ == "__main__":
    ft.app(target=principal)