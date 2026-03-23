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
# TEMAS  —  paletas oscura y clara
# ══════════════════════════════════════════════════════════════════════════════

TEMAS = {
    "dark": {
        "bg":            "#070C14",
        "sidebar":       "#0D1421",
        "topbar":        "#0D1421",
        "surface":       "#111827",
        "border":        "#1A2535",
        "text_primary":  "#E2E8F0",
        "text_muted":    "#64748B",
        "text_hint":     "#334155",
        "accent":        "#38BDF8",
        "accent_dim":    "#0EA5E9",
        "avatar_bg":     "#1E3A5F",
        "avatar_border": "#2563EB",
        "icon_theme":    ft.Icons.LIGHT_MODE,
        "ft_mode":       ft.ThemeMode.DARK,
    },
    "light": {
        "bg":            "#F1F5F9",
        "sidebar":       "#FFFFFF",
        "topbar":        "#FFFFFF",
        "surface":       "#F8FAFC",
        "border":        "#E2E8F0",
        "text_primary":  "#0F172A",
        "text_muted":    "#64748B",
        "text_hint":     "#CBD5E1",
        "accent":        "#0EA5E9",
        "accent_dim":    "#0284C7",
        "avatar_bg":     "#DBEAFE",
        "avatar_border": "#93C5FD",
        "icon_theme":    ft.Icons.DARK_MODE,
        "ft_mode":       ft.ThemeMode.LIGHT,
    },
}

# Estado de tema actual (lista para mutabilidad en closures)
_tema_actual = ["light"]


def T(clave: str):
    """Devuelve el valor del tema activo para la clave dada."""
    return TEMAS[_tema_actual[0]][clave]


# Anchos del sidebar
_W_EXPANDED  = 220
_W_COLLAPSED = 60


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def principal(pagina: ft.Page):
    pagina.title       = "La Posada de Daniel C.A."
    pagina.theme_mode  = ft.ThemeMode.LIGHT
    pagina.padding     = 0
    pagina.spacing     = 0
    pagina.window.width      = 1400
    pagina.window.height     = 900
    pagina.window.min_width  = 1100
    pagina.window.min_height = 700
    pagina.bgcolor     = T("bg")

    inicializar_bd()

    sesion_inicio = SesionLocal()
    try:
        config_inicial = cargar_configuracion_bd(sesion_inicio)
    except Exception as error:
        print(f"Error cargando configuración: {error}")
        config_inicial = {}
    finally:
        sesion_inicio.close()

    estado_app = {
        "usuario_activo": None,
        "tasa_cambio":    float(config_inicial.get("exchange_rate", 35.5)),
        "nombre_hotel":   config_inicial.get("hotel_name", "La Posada"),
        "vista_activa":   "dashboard",
    }

    # Referencias mutables a widgets persistentes
    _zona_contenido = ft.Container(expand=True, bgcolor=T("bg"))
    _sidebar_ref    = [None]   # instancia Sidebar
    _topbar_ref     = [None]   # ft.Container topbar
    _topbar_widgets = {}       # controles internos del topbar para repintado

    # ════════════════════════════════════════════════════════════════════════
    # TEMA  —  toggle que repinta sidebar + topbar + fondo en tiempo real
    # ════════════════════════════════════════════════════════════════════════

    def toggle_theme(e):
        _tema_actual[0] = "light" if _tema_actual[0] == "dark" else "dark"

        # Página
        pagina.theme_mode = T("ft_mode")
        pagina.bgcolor    = T("bg")

        # Ícono del botón (el que disparó el evento)
        e.control.icon       = T("icon_theme")
        e.control.icon_color = T("text_muted")
        try:
            e.control.update()
        except Exception:
            pass

        # Sidebar
        if _sidebar_ref[0]:
            _sidebar_ref[0].aplicar_tema()

        # Topbar
        _repintar_topbar()

        # Zona de contenido
        _zona_contenido.bgcolor = T("bg")
        try:
            _zona_contenido.update()
        except Exception:
            pass

        pagina.update()

    # ════════════════════════════════════════════════════════════════════════
    # LÓGICA DE NEGOCIO
    # ════════════════════════════════════════════════════════════════════════

    def al_hacer_clic_habitacion(habitacion):
        if habitacion.estado == EstadoHabitacion.FREE:
            from modules.rooms.checkin import DialogoCheckIn
            DialogoCheckIn(pagina, habitacion, al_completar=refrescar_grid).mostrar()
        elif habitacion.estado == EstadoHabitacion.CLEANING:
            _mostrar_dialogo_limpieza(habitacion)
        elif habitacion.estado == EstadoHabitacion.OCCUPIED:
            DialogoDetallesHabitacion(
                pagina, habitacion,
                al_solicitar_checkout=iniciar_checkout,
                al_actualizar_grid=refrescar_grid,
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
                pagina.open(ft.SnackBar(
                    ft.Text(f"Hab. {habitacion.numero} lista"),
                    bgcolor=ft.Colors.GREEN_700,
                ))
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Limpieza — Hab. {habitacion.numero}"),
            content=ft.Text("¿Marcar como disponible?"),
            actions=[
                ft.TextButton("No", on_click=lambda _: pagina.close(dlg)),
                ft.ElevatedButton(
                    "Sí, lista", on_click=marcar_libre,
                    bgcolor=ft.Colors.GREEN_700, color="white",
                ),
            ],
        )
        pagina.open(dlg)

    def iniciar_checkout(habitacion):
        from modules.rooms.checkout import CheckOutWizard
        CheckOutWizard(pagina, habitacion,
                       al_completar=lambda _: refrescar_grid()).mostrar()

    def refrescar_grid():
        if estado_app["vista_activa"] == "dashboard":
            _mostrar_dashboard()

    def _mostrar_dashboard():
        try:
            cuadricula = GridHabitaciones(estado_app, al_hacer_clic_habitacion)
            _zona_contenido.content = ft.Container(
                content=cuadricula.construir(),
                expand=True,
                bgcolor=T("bg"),
            )
            _zona_contenido.update()
        except Exception as e:
            print(f"Error en dashboard: {e}")
            _zona_contenido.content = ft.Text(f"Error: {e}", color="red")
            _zona_contenido.update()

    def cambiar_vista(nombre_vista: str):
        estado_app["vista_activa"] = nombre_vista
        if _sidebar_ref[0]:
            _sidebar_ref[0].actualizar_activo(nombre_vista)

        if nombre_vista == "configuracion":
            from modules.finance.cash_management import PantallaGestionCaja
            _zona_contenido.content = PantallaGestionCaja(pagina, estado_app)
        elif nombre_vista == "bitacora":
            from modules.finance.pantalla_bitacora import PantallaBitacora
            _zona_contenido.content = PantallaBitacora(pagina, estado_app)
        elif nombre_vista == "reservaciones":
            from modules.rooms.reservaciones import PantallaReservaciones
            _zona_contenido.content = PantallaReservaciones(
                pagina, estado_app, al_actualizar=refrescar_grid)
        elif nombre_vista == "pendientes":
            from modules.finance.panel_pendientes import abrir_modal_pendientes
            abrir_modal_pendientes(pagina, estado_app)
            return
        else:
            _mostrar_dashboard()
            return
        _zona_contenido.update()

    def cerrar_sesion():
        sesion = SesionLocal()
        try:
            turno = sesion.query(Turno).filter(Turno.activo == True).first()
            id_turno = turno.id if turno else None
        finally:
            sesion.close()
        if id_turno:
            from modules.finance.shift_closing import DialogoCierreTurno
            DialogoCierreTurno(pagina=pagina, id_turno=id_turno,
                               al_cerrar_turno=_ejecutar_cierre_sesion).mostrar()
        else:
            _ejecutar_cierre_sesion()

    def _ejecutar_cierre_sesion():
        estado_app["usuario_activo"] = None
        mostrar_login()

    # ════════════════════════════════════════════════════════════════════════
    # SIDEBAR  —  colapsable con animación suave
    # ════════════════════════════════════════════════════════════════════════

    class Sidebar(ft.Container):

        def __init__(self):
            super().__init__()
            self._activo     = "dashboard"
            self._items_refs = {}   # vista -> ft.Container del ítem
            self._expandido  = True

            # Referencias a widgets que se repintan con el tema
            self._logo_badge  = None
            self._logo_texto  = None
            self._btn_toggle  = None
            self._avatar      = None
            self._user_texto  = None
            self._btn_logout  = None
            self._divisor_bot = None

            self._construir()

        # ── Construcción ──────────────────────────────────────────────────

        def _construir(self):
            self.width        = _W_EXPANDED
            self.bgcolor      = T("sidebar")
            self.border       = ft.border.only(
                right=ft.border.BorderSide(1, T("border"))
            )
            self.animate_size = ft.Animation(220, ft.AnimationCurve.EASE_IN_OUT)

            self._btn_toggle = ft.IconButton(
                icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
                icon_size=18,
                icon_color=T("text_muted"),
                tooltip="Colapsar menú",
                on_click=self._toggle_colapso,
            )

            logo_sec  = self._logo_section()
            nav_sec   = self._nav_section()
            bot_sec   = self._bottom_section()

            self.content = ft.Column(
                controls=[
                    logo_sec,
                    ft.Container(height=8),
                    nav_sec,
                    ft.Container(expand=True),
                    bot_sec,
                ],
                spacing=0,
                expand=True,
            )

        def _logo_section(self) -> ft.Container:
            self._logo_badge = ft.Container(
                content=ft.Text("LP", size=14,
                                weight=ft.FontWeight.W_800,
                                color="#FFFFFF"),
                width=36, height=36,
                bgcolor=T("accent_dim"),
                border_radius=10,
                alignment=ft.alignment.center,
            )
            self._logo_texto = ft.Column([
                ft.Text("La Posada", size=13,
                        weight=ft.FontWeight.W_700,
                        color=T("text_primary")),
                ft.Text("de Daniel C.A.", size=9,
                        color=T("text_muted")),
            ], spacing=0, visible=True)

            return ft.Container(
                content=ft.Row([
                    self._logo_badge,
                    self._logo_texto,
                    ft.Container(expand=True),
                    self._btn_toggle,
                ], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(horizontal=12, vertical=16),
                border=ft.border.only(
                    bottom=ft.border.BorderSide(1, T("border"))
                ),
            )

        def _nav_item(self, vista: str, label: str, icono) -> ft.Container:
            activo = (self._activo == vista)
            icono_ctrl = ft.Icon(
                icono, size=18,
                color=T("accent") if activo else T("text_muted"),
            )
            texto_ctrl = ft.Text(
                label, size=13,
                weight=ft.FontWeight.W_600 if activo else ft.FontWeight.W_400,
                color=T("text_primary") if activo else T("text_muted"),
                visible=self._expandido,
            )
            item = ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=icono_ctrl,
                            width=28,
                            alignment=ft.alignment.center,
                        ),
                        texto_ctrl,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=(ft.Colors.with_opacity(0.08, T("accent"))
                         if activo else ft.Colors.TRANSPARENT),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=10, vertical=10),
                margin=ft.margin.symmetric(horizontal=8, vertical=2),
                border=(ft.border.all(1, ft.Colors.with_opacity(0.15, T("accent")))
                        if activo else None),
                tooltip=None if self._expandido else label,
                on_click=lambda _, v=vista: cambiar_vista(v),
                on_hover=self._hover_item,
                animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
            )
            self._items_refs[vista] = item
            return item

        def _nav_section(self) -> ft.Column:
            items = [
                ("dashboard",     "Inicio",        ft.Icons.GRID_VIEW_ROUNDED),
                ("reservaciones", "Reservas",      ft.Icons.EVENT_AVAILABLE_ROUNDED),
                ("pendientes",    "Pendientes",    ft.Icons.PENDING_ACTIONS_ROUNDED),
                ("bitacora",      "Bitácora",      ft.Icons.HISTORY_ROUNDED),
                ("configuracion", "Configuración", ft.Icons.SETTINGS_ROUNDED),
            ]
            return ft.Column(
                controls=[self._nav_item(v, l, i) for v, l, i in items],
                spacing=0,
            )

        def _bottom_section(self) -> ft.Container:
            info    = estado_app.get("usuario_activo") or {}
            nombre  = info.get("nombre_completo", "Usuario")
            rol     = info.get("rol", "")
            initials= "".join(p[0].upper() for p in nombre.split()[:2]) if nombre else "??"

            self._avatar = ft.Container(
                content=ft.Text(initials, size=11,
                                weight=ft.FontWeight.W_700,
                                color="#FFFFFF"),
                width=32, height=32,
                bgcolor=T("avatar_bg"),
                border_radius=8,
                alignment=ft.alignment.center,
                border=ft.border.all(1, T("avatar_border")),
            )
            self._user_texto = ft.Column([
                ft.Text(nombre, size=11, weight=ft.FontWeight.W_600,
                        color=T("text_primary"),
                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                ft.Text(rol, size=9, color=T("text_muted")),
            ], spacing=0, expand=True, visible=self._expandido)

            self._btn_logout = ft.IconButton(
                icon=ft.Icons.LOGOUT_ROUNDED,
                icon_size=15,
                icon_color=T("text_hint"),
                tooltip="Cerrar sesión",
                visible=self._expandido,
                on_click=lambda _: cerrar_sesion(),
            )
            self._divisor_bot = ft.Divider(height=1, color=T("border"))

            return ft.Container(
                content=ft.Column([
                    self._divisor_bot,
                    ft.Container(
                        content=ft.Row([
                            self._avatar,
                            self._user_texto,
                            self._btn_logout,
                        ], spacing=8),
                        padding=ft.padding.symmetric(horizontal=10, vertical=12),
                    ),
                ], spacing=0),
            )

        # ── Colapso / expansión ───────────────────────────────────────────

        _LABELS = {
            "dashboard":     "Inicio",
            "reservaciones": "Reservas",
            "pendientes":    "Pendientes",
            "bitacora":      "Bitácora",
            "configuracion": "Configuración",
        }

        def _toggle_colapso(self, _):
            self._expandido = not self._expandido
            exp = self._expandido

            # Ancho del contenedor
            self.width = _W_EXPANDED if exp else _W_COLLAPSED

            # Botón toggle
            self._btn_toggle.icon    = (ft.Icons.CHEVRON_LEFT_ROUNDED if exp
                                        else ft.Icons.CHEVRON_RIGHT_ROUNDED)
            self._btn_toggle.tooltip = "Colapsar menú" if exp else "Expandir menú"

            # Texto del logo
            self._logo_texto.visible = exp

            # Ítems de navegación
            for vista, item in self._items_refs.items():
                row = item.content
                if row and len(row.controls) > 1:
                    row.controls[1].visible = exp   # texto label
                item.padding = ft.padding.symmetric(
                    horizontal=10 if exp else 0, vertical=10
                )
                item.margin = ft.margin.symmetric(
                    horizontal=8 if exp else 4, vertical=2
                )
                item.tooltip = None if exp else self._LABELS.get(vista, vista)

            # Sección inferior
            self._user_texto.visible = exp
            self._btn_logout.visible = exp

            self.update()

        # ── Hover ─────────────────────────────────────────────────────────

        def _hover_item(self, e):
            for k, v in self._items_refs.items():
                if v == e.control:
                    if k == self._activo:
                        return
                    break
            e.control.bgcolor = (
                ft.Colors.with_opacity(0.05, "#FFFFFF")
                if e.data == "true"
                else ft.Colors.TRANSPARENT
            )
            e.control.update()

        # ── Actualizar ítem activo ─────────────────────────────────────────

        def actualizar_activo(self, nueva_vista: str):
            anterior     = self._activo
            self._activo = nueva_vista

            for vista, es_activo in [(anterior, False), (nueva_vista, True)]:
                if vista not in self._items_refs:
                    continue
                item = self._items_refs[vista]
                item.bgcolor = (ft.Colors.with_opacity(0.08, T("accent"))
                                if es_activo else ft.Colors.TRANSPARENT)
                item.border  = (ft.border.all(1, ft.Colors.with_opacity(0.15, T("accent")))
                                if es_activo else None)
                row = item.content
                if row and len(row.controls) >= 2:
                    ic = row.controls[0]
                    tx = row.controls[1]
                    if ic.content:
                        ic.content.color = T("accent") if es_activo else T("text_muted")
                    tx.color  = T("text_primary") if es_activo else T("text_muted")
                    tx.weight = (ft.FontWeight.W_600 if es_activo
                                 else ft.FontWeight.W_400)
                try:
                    item.update()
                except Exception:
                    pass

        # ── Repintar colores al cambiar tema ──────────────────────────────

        def aplicar_tema(self):
            self.bgcolor = T("sidebar")
            self.border  = ft.border.only(
                right=ft.border.BorderSide(1, T("border"))
            )

            # Logo
            if self._logo_badge:
                self._logo_badge.bgcolor = T("accent_dim")
            if self._logo_texto and self._logo_texto.controls:
                self._logo_texto.controls[0].color = T("text_primary")
                self._logo_texto.controls[1].color = T("text_muted")

            # Botón toggle
            if self._btn_toggle:
                self._btn_toggle.icon_color = T("text_muted")

            # Ítems de navegación
            for vista, item in self._items_refs.items():
                activo = (vista == self._activo)
                item.bgcolor = (ft.Colors.with_opacity(0.08, T("accent"))
                                if activo else ft.Colors.TRANSPARENT)
                item.border  = (ft.border.all(1, ft.Colors.with_opacity(0.15, T("accent")))
                                if activo else None)
                row = item.content
                if row and len(row.controls) >= 2:
                    ic = row.controls[0]
                    tx = row.controls[1]
                    if ic.content:
                        ic.content.color = T("accent") if activo else T("text_muted")
                    tx.color = T("text_primary") if activo else T("text_muted")

            # Avatar y usuario
            if self._avatar:
                self._avatar.bgcolor = T("avatar_bg")
                self._avatar.border  = ft.border.all(1, T("avatar_border"))
            if self._user_texto and self._user_texto.controls:
                self._user_texto.controls[0].color = T("text_primary")
                self._user_texto.controls[1].color = T("text_muted")
            if self._btn_logout:
                self._btn_logout.icon_color = T("text_hint")
            if self._divisor_bot:
                self._divisor_bot.color = T("border")

            try:
                self.update()
            except Exception:
                pass

    # ════════════════════════════════════════════════════════════════════════
    # TOPBAR
    # ════════════════════════════════════════════════════════════════════════

    def _construir_topbar() -> ft.Container:
        info_usuario = estado_app.get("usuario_activo") or {}
        nombre_user  = info_usuario.get("nombre_completo", "Usuario")
        tasa         = estado_app.get("tasa_cambio", 35.5)

        # Controles con referencias guardadas para repintado
        ico_tasa  = ft.Icon(ft.Icons.CURRENCY_EXCHANGE, size=12, color=T("accent"))
        txt_tasa  = ft.Text(f"Bs. {tasa:,.2f} / USD", size=11,
                            color=T("accent"), weight=ft.FontWeight.W_600)
        chip_tasa = ft.Container(
            content=ft.Row([ico_tasa, txt_tasa], spacing=5),
            bgcolor=ft.Colors.with_opacity(0.08, T("accent")),
            border=ft.border.all(1, ft.Colors.with_opacity(0.2, T("accent"))),
            border_radius=20,
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
        )

        btn_theme = ft.IconButton(
            icon=T("icon_theme"),
            icon_size=16,
            icon_color=T("text_muted"),
            tooltip="Cambiar tema",
            on_click=toggle_theme,
        )

        txt_hotel = ft.Text(estado_app["nombre_hotel"], size=13,
                            weight=ft.FontWeight.W_500, color=T("text_muted"))
        txt_panel = ft.Text("Panel de habitaciones", size=13,
                            weight=ft.FontWeight.W_600, color=T("text_primary"))
        ico_chev  = ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=14,
                            color=T("text_hint"))
        txt_user  = ft.Text(nombre_user, size=12, weight=ft.FontWeight.W_600,
                            color=T("text_primary"))
        sep       = ft.Container(width=1, height=24, bgcolor=T("border"),
                                 margin=ft.margin.symmetric(horizontal=6))

        # Guardar referencias para repintado posterior
        _topbar_widgets.update({
            "ico_tasa":  ico_tasa,
            "txt_tasa":  txt_tasa,
            "chip_tasa": chip_tasa,
            "btn_theme": btn_theme,
            "txt_hotel": txt_hotel,
            "txt_panel": txt_panel,
            "ico_chev":  ico_chev,
            "txt_user":  txt_user,
            "sep":       sep,
        })

        topbar = ft.Container(
            content=ft.Row([
                ft.Row([txt_hotel, ico_chev, txt_panel], spacing=4),
                ft.Container(expand=True),
                chip_tasa,
                btn_theme,
                ft.IconButton(
                    icon=ft.Icons.NOTIFICATIONS_NONE_ROUNDED,
                    icon_size=18, icon_color=T("text_muted"),
                    tooltip="Notificaciones",
                ),
                sep,
                txt_user,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
            bgcolor=T("topbar"),
            border=ft.border.only(bottom=ft.border.BorderSide(1, T("border"))),
            height=52,
        )
        _topbar_ref[0] = topbar
        return topbar

    def _repintar_topbar():
        tb = _topbar_ref[0]
        w  = _topbar_widgets
        if not tb or not w:
            return

        tb.bgcolor = T("topbar")
        tb.border  = ft.border.only(
            bottom=ft.border.BorderSide(1, T("border"))
        )

        # Chip de tasa
        w["chip_tasa"].bgcolor = ft.Colors.with_opacity(0.08, T("accent"))
        w["chip_tasa"].border  = ft.border.all(
            1, ft.Colors.with_opacity(0.2, T("accent"))
        )
        w["ico_tasa"].color = T("accent")
        w["txt_tasa"].color = T("accent")

        # Btn tema (el ícono ya se actualiza en toggle_theme)
        w["btn_theme"].icon_color = T("text_muted")

        # Textos
        w["txt_hotel"].color = T("text_muted")
        w["txt_panel"].color = T("text_primary")
        w["ico_chev"].color  = T("text_hint")
        w["txt_user"].color  = T("text_primary")
        w["sep"].bgcolor     = T("border")

        try:
            tb.update()
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN DE LA INTERFAZ PRINCIPAL
    # ════════════════════════════════════════════════════════════════════════

    def _construir_interfaz_app():
        pagina.clean()

        sidebar = Sidebar()
        _sidebar_ref[0] = sidebar

        topbar = _construir_topbar()

        layout = ft.Row(
            controls=[
                sidebar,
                ft.Column(
                    controls=[
                        topbar,
                        ft.Container(
                            content=_zona_contenido,
                            expand=True,
                            bgcolor=T("bg"),
                        ),
                    ],
                    spacing=0,
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        )

        pagina.add(layout)
        _mostrar_dashboard()

    # ════════════════════════════════════════════════════════════════════════
    # LOGIN Y APERTURA DE TURNO
    # ════════════════════════════════════════════════════════════════════════

    def mostrar_login():
        pagina.clean()
        pagina.bgcolor = TEMAS["dark"]["bg"]
        pagina.add(PantallaLogin(pagina, al_iniciar_sesion_exitoso).construir())

    def al_iniciar_sesion_exitoso(usuario):
        estado_app["usuario_activo"] = usuario
        DialogoAperturaTurno(pagina, usuario,
                             al_completar=al_abrir_turno).mostrar()

    def al_abrir_turno(tasa):
        estado_app["tasa_cambio"] = tasa
        _construir_interfaz_app()

    mostrar_login()


if __name__ == "__main__":
    ft.app(target=principal)