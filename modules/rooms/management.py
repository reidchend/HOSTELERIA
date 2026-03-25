import flet as ft
from datetime import date
from database.models import Habitacion, EstadoHabitacion, Estadia
from database.connection import SesionLocal
from sqlalchemy import cast, Integer
from sqlalchemy.orm import selectinload

# ══════════════════════════════════════════════════════════════════════════════
# PALETA POR ESTADO  —  Colores adaptados para legibilidad en ambos temas
# ══════════════════════════════════════════════════════════════════════════════

_ESTADO_CFG = {
    EstadoHabitacion.FREE: {
        "label":        "DISPONIBLE",
        "dot":          "#22C55E",   
        "num_color":    "#F0FDF4",
        "badge_bg":     "#14532D",
        "badge_text":   "#86EFAC",
        "card_border":  "#166534",
        "card_top":     "#0F2D1A",   
        "card_bot":     "#0A1F12",   
        "glow":         "#22C55E",
        "icono":        ft.Icons.KING_BED_OUTLINED,
        "tipo_color":   "#4ADE80",
    },
    EstadoHabitacion.OCCUPIED: {
        "label":        "OCUPADA",
        "dot":          "#EF4444",
        "num_color":    "#FFF1F1",
        "badge_bg":     "#7F1D1D",
        "badge_text":   "#FCA5A5",
        "card_border":  "#991B1B",
        "card_top":     "#2D0F0F",
        "card_bot":     "#1F0A0A",
        "glow":         "#EF4444",
        "icono":        ft.Icons.PERSON_ROUNDED,
        "tipo_color":   "#F87171",
    },
    EstadoHabitacion.RESERVED: {
        "label":        "RESERVADA",
        "dot":          "#F59E0B",
        "num_color":    "#FFFBEB",
        "badge_bg":     "#78350F",
        "badge_text":   "#FCD34D",
        "card_border":  "#92400E",
        "card_top":     "#2D1F0A",
        "card_bot":     "#1F1408",
        "glow":         "#F59E0B",
        "icono":        ft.Icons.CALENDAR_MONTH_ROUNDED,
        "tipo_color":   "#FCD34D",
    },
    EstadoHabitacion.CLEANING: {
        "label":        "LIMPIEZA",
        "dot":          "#06B6D4",
        "num_color":    "#ECFEFF",
        "badge_bg":     "#164E63",
        "badge_text":   "#67E8F9",
        "card_border":  "#155E75",
        "card_top":     "#0A2029",
        "card_bot":     "#06151C",
        "glow":         "#06B6D4",
        "icono":        ft.Icons.CLEANING_SERVICES_ROUNDED,
        "tipo_color":   "#22D3EE",
    },
    EstadoHabitacion.MAINTENANCE: {
        "label":        "MTTO.",
        "dot":          "#8B5CF6",
        "num_color":    "#F5F3FF",
        "badge_bg":     "#3B0764",
        "badge_text":   "#C4B5FD",
        "card_border":  "#4C1D95",
        "card_top":     "#160D29",
        "card_bot":     "#0E0818",
        "glow":         "#8B5CF6",
        "icono":        ft.Icons.BUILD_CIRCLE_OUTLINED,
        "tipo_color":   "#A78BFA",
    },
}

_TIPO_ABREV = {
    "MATRIMONIAL": "MAT",
    "DOBLE":       "DOB",
    "SUITE":       "SUI",
    "TRIPLE":      "TRI",
    "QUINTUPLE":   "QUI",
    "INDIVIDUAL":  "IND",
}

# ══════════════════════════════════════════════════════════════════════════════
# GRID DE HABITACIONES
# ══════════════════════════════════════════════════════════════════════════════

class GridHabitaciones:
    def __init__(self, estado_app: dict, al_hacer_clic):
        self.estado_app    = estado_app
        self.al_hacer_clic = al_hacer_clic

        self.grid = ft.GridView(
            expand=True,
            max_extent=140, 
            child_aspect_ratio=0.82,
            spacing=12,
            run_spacing=12,
            padding=ft.padding.all(20),
            # SE ELIMINÓ bgcolor="surface" de aquí porque GridView no lo soporta
            # y era lo que estaba causando que el grid desapareciera por completo.
        )

    def _tarjeta(self, hab: Habitacion) -> ft.Container:
        cfg = _ESTADO_CFG.get(hab.estado, _ESTADO_CFG[EstadoHabitacion.FREE])
        tiene_deuda = False
        sale_hoy    = False
        nombre_h    = ""

        if hab.estado == EstadoHabitacion.OCCUPIED and hab.estadias_activas:
            est = hab.estadias_activas[0]
            tiene_deuda = any(not fl.cancelada for fl in (est.folio_lineas or []))
            if est.salida:
                salida_d = est.salida.date() if hasattr(est.salida, "date") else est.salida
                sale_hoy = (salida_d == date.today())
            if est.huespedes:
                nombre_h = est.huespedes[0].nombre.split()[0].upper()

        tipo_abrev = _TIPO_ABREV.get((hab.tipo or "").upper(), (hab.tipo or "???")[:3].upper())
        num_str = str(hab.numero).zfill(2)

        fila_top = ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text(tipo_abrev, size=8, weight=ft.FontWeight.W_700, color=cfg["tipo_color"]),
                    bgcolor=cfg["badge_bg"],
                    padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    border_radius=15,
                    border=ft.border.all(1, cfg["card_border"]),
                ),
                ft.Icon(cfg["icono"], size=14, color=cfg["tipo_color"], opacity=0.7),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        numero_widget = ft.Text(num_str, size=34, weight=ft.FontWeight.W_900, color=cfg["num_color"], height=40)

        estado_row = ft.Row(
            controls=[
                ft.Container(width=6, height=6, bgcolor=cfg["dot"], border_radius=10),
                ft.Text(cfg["label"], size=8, weight=ft.FontWeight.W_700, color=cfg["dot"]),
            ],
            spacing=4,
        )

        nombre_widget = ft.Text(nombre_h, size=8, weight=ft.FontWeight.W_600, color=cfg["badge_text"], overflow=ft.TextOverflow.ELLIPSIS) if nombre_h else ft.Container(height=0)

        deuda_badge = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED, size=8, color="#FDE047"), ft.Text("DEUDA", size=7, weight="bold", color="#FDE047")], spacing=2),
            bgcolor="#422006", padding=ft.padding.symmetric(horizontal=5, vertical=2), border_radius=15, visible=tiene_deuda
        )

        salida_badge = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.FLIGHT_TAKEOFF_ROUNDED, size=8, color="#FFFFFF"), ft.Text("HOY", size=7, weight="bold", color="#FFFFFF")], spacing=2),
            bgcolor="#DC2626", padding=ft.padding.symmetric(horizontal=5, vertical=2), border_radius=15, visible=sale_hoy
        )

        return ft.Container(
            content=ft.Column([fila_top, numero_widget, nombre_widget, estado_row, ft.Row([deuda_badge, salida_badge], spacing=3, wrap=True)], spacing=3, expand=True),
            padding=ft.padding.all(10),
            border_radius=12,
            border=ft.border.all(1.2, cfg["card_border"]),
            gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=[cfg["card_top"], cfg["card_bot"]]),
            on_click=lambda _: self.al_hacer_clic(hab),
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            scale=1.0,
        )

    def construir(self) -> ft.Container:
        sesion = SesionLocal()
        try:
            habs = (
                sesion.query(Habitacion)
                .options(
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.huespedes),
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.folio_lineas),
                )
                .order_by(cast(Habitacion.numero, Integer))
                .all()
            )

            self.grid.controls = [self._tarjeta(h) for h in habs]

            # Conteo de estados
            conteos = {est: 0 for est in _ESTADO_CFG.keys()}
            for h in habs:
                conteos[h.estado] = conteos.get(h.estado, 0) + 1

            chips_resumen = []
            for estado, cfg in _ESTADO_CFG.items():
                n = conteos.get(estado, 0)
                chips_resumen.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Container(width=5, height=5, bgcolor=cfg["dot"], border_radius=10),
                            ft.Text(str(n), size=11, weight="bold", color="on_surface"),
                            ft.Text(cfg["label"], size=8, color="on_surface_variant"),
                        ], spacing=5),
                        bgcolor="surfacevariant",
                        border=ft.border.all(1, "outlinevariant"),
                        border_radius=15,
                        padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    )
                )

            # Barra superior (Resumen)
            barra_resumen = ft.Container(
                content=ft.Row([
                    ft.Row([
                        ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=13, color="on_surface_variant"),
                        ft.Text(f" {len(habs)} hab.", size=10, color="on_surface_variant"),
                    ]),
                    ft.VerticalDivider(width=1, color="outline"),
                    ft.Row(controls=chips_resumen, spacing=6, wrap=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(horizontal=20, vertical=10),
                bgcolor="surface", # Coincide con el fondo principal
                border=ft.border.only(bottom=ft.border.BorderSide(1, "outlinevariant")),
                margin=0,
            )

            # Contenedor envolvente principal: Este es el que mata el fondo negro de la app principal
            return ft.Container(
                expand=True,
                bgcolor="surface", # Esto asegura que no haya fondo negro en toda esta área
                margin=0,
                padding=0,
                content=ft.Column(
                    controls=[
                        barra_resumen, 
                        # Colocamos el grid directamente en un container expandido
                        ft.Container(
                            content=self.grid,
                            expand=True,
                            margin=0,
                            padding=0
                        )
                    ], 
                    spacing=0, 
                    expand=True
                )
            )

        except Exception as e:
            print(f"Error en GridHabitaciones: {e}")
            return ft.Container(content=ft.Text(f"Error al cargar mapa: {e}", color="red"))
        finally:
            sesion.close()