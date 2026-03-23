import flet as ft
from datetime import date
from database.models import Habitacion, EstadoHabitacion, Estadia
from database.connection import SesionLocal
from sqlalchemy import cast, Integer
from sqlalchemy.orm import selectinload

class GridHabitaciones:
    """
    Cuadrícula visual del mapa de habitaciones con diseño moderno y minimalista.
    Se eliminan buscadores para priorizar la limpieza visual.
    """

    def __init__(self, estado_app: dict, al_hacer_clic):
        self.estado_app = estado_app
        self.al_hacer_clic = al_hacer_clic
        self.habitaciones_data = []
        
        # Grid principal con espaciado amplio
        self.grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=180, 
            child_aspect_ratio=0.8,
            spacing=20,
            run_spacing=20,
            padding=20,
        )

    def _obtener_estilos(self, habitacion):
        """Mapeo de estilos modernos (Colores más suaves y profesionales)."""
        estilos = {
            EstadoHabitacion.FREE: {
                "fondo": "#F0FDF4", # Green 50
                "acento": "#16A34A", # Green 600
                "texto": "#14532D",
                "icono": ft.Icons.BED_OUTLINED, 
                "etiqueta": "Disponible"
            },
            EstadoHabitacion.OCCUPIED: {
                "fondo": "#FEF2F2", # Red 50
                "acento": "#DC2626", # Red 600
                "texto": "#7F1D1D",
                "icono": ft.Icons.PERSON_ROUNDED, 
                "etiqueta": "Ocupada"
            },
            EstadoHabitacion.RESERVED: {
                "fondo": "#FFFBEB", # Amber 50
                "acento": "#D97706", # Amber 600
                "texto": "#78350F",
                "icono": ft.Icons.CALENDAR_TODAY_ROUNDED, 
                "etiqueta": "Reservada"
            },
            EstadoHabitacion.CLEANING: {
                "fondo": "#ECFEFF", # Cyan 50
                "acento": "#0891B2", # Cyan 600
                "texto": "#164E63",
                "icono": ft.Icons.CLEANING_SERVICES_ROUNDED, 
                "etiqueta": "Limpieza"
            },
            EstadoHabitacion.MAINTENANCE: {
                "fondo": "#F8FAFC", # Slate 50
                "acento": "#475569", # Slate 600
                "texto": "#0F172A",
                "icono": ft.Icons.BUILD_CIRCLE_OUTLINED, 
                "etiqueta": "Mtto."
            },
        }
        return estilos.get(habitacion.estado, estilos[EstadoHabitacion.FREE])

    def crear_tarjeta_habitacion(self, hab: Habitacion):
        """Construye una tarjeta con diseño tipo 'Glassmorphism' o Card Moderno."""
        estilo = self._obtener_estilos(hab)
        
        tiene_pendiente = False
        sale_hoy = False
        nombre_huesped = ""

        if hab.estado == EstadoHabitacion.OCCUPIED and hab.estadias_activas:
            estadia = hab.estadias_activas[0]
            tiene_pendiente = any(not fl.cancelada for fl in (estadia.folio_lineas or []))
            
            if estadia.salida:
                salida_date = estadia.salida.date() if hasattr(estadia.salida, "date") else estadia.salida
                sale_hoy = (salida_date == date.today())
            
            if estadia.huespedes:
                nombre_huesped = estadia.huespedes[0].nombre.split()[0].title()

        # Color especial si tiene deuda
        borde_color = "#EAB308" if tiene_pendiente else estilo["acento"]

        return ft.Container(
            content=ft.Stack([
                ft.Column([
                    # Header: Numero y Badge de Tipo
                    ft.Row([
                        ft.Text(
                            str(hab.numero), 
                            size=22, 
                            weight=ft.FontWeight.BOLD, 
                            color=ft.Colors.BLUE_GREY_900
                        ),
                        ft.Container(
                            content=ft.Text(
                                hab.tipo[:3].upper() if hab.tipo else "STD", 
                                size=9, 
                                weight="bold", 
                                color=estilo["acento"]
                            ),
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=15,
                            border=ft.border.all(1, estilo["acento"]),
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                    ft.Divider(height=1, color=ft.Colors.BLACK12),
                    
                    # Cuerpo central
                    ft.Container(
                        expand=True,
                        alignment=ft.alignment.center,
                        content=ft.Column([
                            ft.Icon(
                                estilo["icono"], 
                                color=estilo["acento"], 
                                size=32,
                                opacity=0.8
                            ),
                            ft.Text(
                                nombre_huesped if nombre_huesped else estilo["etiqueta"],
                                size=12,
                                weight=ft.FontWeight.W_500,
                                color=ft.Colors.BLUE_GREY_700,
                                text_align="center",
                            ),
                            # Indicador de Deuda / Pendiente
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.MONETIZATION_ON_OUTLINED, size=12, color="#854D0E"),
                                    ft.Text("PAGO PENDIENTE", size=8, weight="bold", color="#854D0E"),
                                ], spacing=3, alignment="center"),
                                bgcolor="#FEF9C3",
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border_radius=20,
                                visible=tiene_pendiente
                            )
                        ], horizontal_alignment="center", spacing=8)
                    ),
                ], spacing=10), # Se quitó 'padding' de aquí
                
                # Badge "Salida Hoy" (Esquina superior derecha)
                ft.Container(
                    content=ft.Icon(ft.Icons.NOTIFICATION_IMPORTANT_ROUNDED, size=14, color="white"),
                    bgcolor="#F97316",
                    shape=ft.BoxShape.CIRCLE,
                    padding=5,
                    right=-5,
                    top=-5,
                    visible=sale_hoy,
                    tooltip="Check-out hoy"
                )
            ]),
            bgcolor=ft.Colors.WHITE,
            padding=15, # El padding se aplica aquí, al Container que envuelve la Column
            border_radius=16,
            border=ft.border.all(1.5, borde_color if hab.estado != EstadoHabitacion.FREE else ft.Colors.TRANSPARENT),
            shadow=ft.BoxShadow(
                blur_radius=15,
                spread_radius=1,
                color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                offset=ft.Offset(0, 5)
            ),
            on_click=lambda _: self.al_hacer_clic(hab),
            on_hover=self._handle_hover,
            animate_scale=ft.Animation(400, ft.AnimationCurve.EASE_OUT_BACK),
            scale=1.0,
        )

    def _handle_hover(self, e):
        e.control.scale = 1.03 if e.data == "true" else 1.0
        # Cambiamos la sombra al hacer hover para dar sensación de elevación
        e.control.shadow = ft.BoxShadow(
            blur_radius=25,
            spread_radius=2,
            color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
            offset=ft.Offset(0, 10)
        ) if e.data == "true" else ft.BoxShadow(
            blur_radius=15,
            spread_radius=1,
            color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
            offset=ft.Offset(0, 5)
        )
        e.control.update()

    def construir(self):
        sesion = SesionLocal()
        try:
            self.habitaciones_data = (
                sesion.query(Habitacion)
                .options(
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.huespedes),
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.folio_lineas)
                )
                .order_by(cast(Habitacion.numero, Integer))
                .all()
            )
            
            self.grid.controls = [self.crear_tarjeta_habitacion(h) for h in self.habitaciones_data]
            
            return ft.Container(
                content=self.grid,
                expand=True,
                bgcolor="#F8FAFC", 
            )
            
        except Exception as e:
            print(f"DEBUG ERROR GridHabitaciones: {e}")
            import traceback
            traceback.print_exc()
            return ft.Text(f"Error al cargar mapa: {e}", color="red")
        finally:
            sesion.close()