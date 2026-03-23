import flet as ft
from datetime import date
from database.models import Habitacion, EstadoHabitacion, Estadia
from database.connection import SesionLocal
from sqlalchemy import cast, Integer
from sqlalchemy.orm import selectinload


# ══════════════════════════════════════════════════════════════════════════════
# PALETA POR ESTADO  —  colores premium oscuros
# ══════════════════════════════════════════════════════════════════════════════

_ESTADO_CFG = {
    EstadoHabitacion.FREE: {
        "label":        "DISPONIBLE",
        "dot":          "#22C55E",   # verde esmeralda
        "num_color":    "#F0FDF4",
        "badge_bg":     "#14532D",
        "badge_text":   "#86EFAC",
        "card_border":  "#166534",
        "card_top":     "#0F2D1A",   # gradiente arriba
        "card_bot":     "#0A1F12",   # gradiente abajo
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

# Abreviaturas de tipo
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
    """
    Mapa de habitaciones con diseño premium oscuro.
    Tarjetas con gradiente por estado, número grande, glow on-hover,
    badge de tipo, indicadores de deuda y salida hoy.
    """

    def __init__(self, estado_app: dict, al_hacer_clic):
        self.estado_app    = estado_app
        self.al_hacer_clic = al_hacer_clic

        self.grid = ft.GridView(
            expand=True,
            runs_count=6,
            max_extent=160,
            child_aspect_ratio=0.78,
            spacing=14,
            run_spacing=14,
            padding=ft.padding.symmetric(horizontal=24, vertical=18),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # TARJETA INDIVIDUAL
    # ─────────────────────────────────────────────────────────────────────────

    def _tarjeta(self, hab: Habitacion) -> ft.Container:
        cfg = _ESTADO_CFG.get(hab.estado, _ESTADO_CFG[EstadoHabitacion.FREE])

        # ── Extraer info de la estadía ────────────────────────────────────────
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

        # ── Abreviatura del tipo ──────────────────────────────────────────────
        tipo_abrev = _TIPO_ABREV.get(
            (hab.tipo or "").upper(),
            (hab.tipo or "???")[:3].upper()
        )

        # ── Número formateado (con cero a la izquierda) ───────────────────────
        num_str = str(hab.numero).zfill(2)

        # ── Contenido interno de la tarjeta ───────────────────────────────────

        # Fila superior: tipo + icono
        fila_top = ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text(
                        tipo_abrev,
                        size=9,
                        weight=ft.FontWeight.W_700,
                        color=cfg["tipo_color"],
                        font_family="Courier New",
                    ),
                    bgcolor=cfg["badge_bg"],
                    padding=ft.padding.symmetric(horizontal=7, vertical=3),
                    border_radius=20,
                    border=ft.border.all(1, cfg["card_border"]),
                ),
                ft.Icon(cfg["icono"], size=15, color=cfg["tipo_color"], opacity=0.8),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # Número grande
        numero_widget = ft.Text(
            num_str,
            size=42,
            weight=ft.FontWeight.W_900,
            color=cfg["num_color"],
            font_family="Courier New",
            height=52,
        )

        # Estado con dot
        dot = ft.Container(
            width=7, height=7,
            bgcolor=cfg["dot"],
            border_radius=10,
            shadow=ft.BoxShadow(
                blur_radius=8,
                color=cfg["glow"],
                spread_radius=1,
            ),
        )
        estado_row = ft.Row(
            controls=[
                dot,
                ft.Text(
                    cfg["label"],
                    size=8,
                    weight=ft.FontWeight.W_700,
                    color=cfg["dot"],
                ),
            ],
            spacing=5,
        )

        # Nombre del huésped (si aplica)
        nombre_widget = ft.Text(
            nombre_h,
            size=9,
            weight=ft.FontWeight.W_600,
            color=cfg["badge_text"],
            opacity=0.9,
            overflow=ft.TextOverflow.ELLIPSIS,
        ) if nombre_h else ft.Container(height=0)

        # Badge deuda
        deuda_badge = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED, size=9, color="#FDE047"),
                ft.Text("DEUDA", size=7, weight="bold", color="#FDE047"),
            ], spacing=3),
            bgcolor="#422006",
            padding=ft.padding.symmetric(horizontal=6, vertical=3),
            border_radius=20,
            border=ft.border.all(1, "#854D0E"),
            visible=tiene_deuda,
        )

        # Badge salida hoy
        salida_badge = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.FLIGHT_TAKEOFF_ROUNDED, size=9, color="#FFFFFF"),
                ft.Text("HOY", size=7, weight="bold", color="#FFFFFF"),
            ], spacing=3),
            bgcolor="#DC2626",
            padding=ft.padding.symmetric(horizontal=6, vertical=3),
            border_radius=20,
            border=ft.border.all(1, "#EF4444"),
            visible=sale_hoy,
        )

        # ── Columna interna ───────────────────────────────────────────────────
        columna = ft.Column(
            controls=[
                fila_top,
                numero_widget,
                nombre_widget,
                estado_row,
                ft.Row(
                    controls=[deuda_badge, salida_badge],
                    spacing=4, wrap=True,
                ),
            ],
            spacing=4,
            expand=True,
        )

        # ── Contenedor final con gradiente ────────────────────────────────────
        return ft.Container(
            content=columna,
            padding=ft.padding.all(12),
            border_radius=16,
            border=ft.border.all(1.5, cfg["card_border"]),
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[cfg["card_top"], cfg["card_bot"]],
            ),
            shadow=ft.BoxShadow(
                blur_radius=0,
                spread_radius=0,
                color=ft.Colors.TRANSPARENT,
                offset=ft.Offset(0, 0),
            ),
            on_click=lambda _: self.al_hacer_clic(hab),
            on_hover=self._hover,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            scale=1.0,
        )

    def _hover(self, e: ft.HoverEvent):
        c = e.control
        if e.data == "true":
            c.shadow = ft.BoxShadow(
                blur_radius=24,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.35, "#FFFFFF"),
                offset=ft.Offset(0, 6),
            )
            c.scale  = 1.04
            c.border = ft.border.all(
                2.0,
                ft.Colors.with_opacity(0.7, "#FFFFFF"),
            )
        else:
            # Restaurar border original
            hab_estado = None
            try:
                # Leer el estado desde el gradiente (inferir cfg desde el color)
                top = c.gradient.colors[0]
                for est, cfg in _ESTADO_CFG.items():
                    if cfg["card_top"] == top:
                        hab_estado = est
                        break
            except Exception:
                pass

            border_color = _ESTADO_CFG.get(
                hab_estado, _ESTADO_CFG[EstadoHabitacion.FREE]
            )["card_border"] if hab_estado else "#166534"

            c.shadow = ft.BoxShadow(
                blur_radius=0, spread_radius=0,
                color=ft.Colors.TRANSPARENT,
                offset=ft.Offset(0, 0),
            )
            c.scale  = 1.0
            c.border = ft.border.all(1.5, border_color)
        c.update()

    # ─────────────────────────────────────────────────────────────────────────
    # LEYENDA DE ESTADOS
    # ─────────────────────────────────────────────────────────────────────────

    def _leyenda(self) -> ft.Container:
        items = []
        for estado, cfg in _ESTADO_CFG.items():
            items.append(
                ft.Row([
                    ft.Container(
                        width=8, height=8,
                        bgcolor=cfg["dot"],
                        border_radius=10,
                    ),
                    ft.Text(
                        cfg["label"],
                        size=10,
                        color="#94A3B8",
                        weight=ft.FontWeight.W_500,
                    ),
                ], spacing=6)
            )

        return ft.Container(
            content=ft.Row(controls=items, spacing=18, wrap=True),
            padding=ft.padding.symmetric(horizontal=24, vertical=10),
            bgcolor="#0D1117",
            border=ft.border.only(top=ft.border.BorderSide(1, "#1E293B")),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUIR
    # ─────────────────────────────────────────────────────────────────────────

    def construir(self) -> ft.Column:
        sesion = SesionLocal()
        try:
            habs = (
                sesion.query(Habitacion)
                .options(
                    selectinload(Habitacion.estadias_activas)
                        .selectinload(Estadia.huespedes),
                    selectinload(Habitacion.estadias_activas)
                        .selectinload(Estadia.folio_lineas),
                )
                .order_by(cast(Habitacion.numero, Integer))
                .all()
            )

            self.grid.controls = [self._tarjeta(h) for h in habs]

            # ── Contadores por estado ─────────────────────────────────────────
            conteos = {}
            for h in habs:
                conteos[h.estado] = conteos.get(h.estado, 0) + 1

            chips_resumen = []
            for estado, cfg in _ESTADO_CFG.items():
                n = conteos.get(estado, 0)
                chips_resumen.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                width=6, height=6,
                                bgcolor=cfg["dot"],
                                border_radius=10,
                                shadow=ft.BoxShadow(
                                    blur_radius=6,
                                    color=cfg["glow"],
                                    spread_radius=0,
                                ),
                            ),
                            ft.Text(
                                str(n),
                                size=13,
                                weight=ft.FontWeight.W_700,
                                color="#F1F5F9",
                            ),
                            ft.Text(
                                cfg["label"],
                                size=10,
                                color="#64748B",
                                weight=ft.FontWeight.W_500,
                            ),
                        ], spacing=6),
                        bgcolor="#0D1117",
                        border=ft.border.all(1, "#1E293B"),
                        border_radius=20,
                        padding=ft.padding.symmetric(horizontal=12, vertical=7),
                    )
                )

            # ── Barra de resumen superior ─────────────────────────────────────
            barra_resumen = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Row([
                            ft.Icon(
                                ft.Icons.GRID_VIEW_ROUNDED,
                                size=14, color="#475569",
                            ),
                            ft.Text(
                                f"  {len(habs)} habitaciones",
                                size=11, color="#475569",
                                weight=ft.FontWeight.W_500,
                            ),
                        ], spacing=0),
                        ft.Container(
                            width=1, height=18,
                            bgcolor="#1E293B",
                            margin=ft.margin.symmetric(horizontal=10),
                        ),
                        ft.Row(
                            controls=chips_resumen,
                            spacing=8,
                            wrap=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=24, vertical=12),
                bgcolor="#080D14",
                border=ft.border.only(bottom=ft.border.BorderSide(1, "#1E293B")),
            )

            # ── Contenedor del grid con fondo oscuro ──────────────────────────
            grid_container = ft.Container(
                content=self.grid,
                expand=True,
                bgcolor="#080D14",
            )

            return ft.Column(
                controls=[barra_resumen, grid_container],
                spacing=0,
                expand=True,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return ft.Column([
                ft.Text(f"Error al cargar mapa: {e}", color="red")
            ])
        finally:
            sesion.close()