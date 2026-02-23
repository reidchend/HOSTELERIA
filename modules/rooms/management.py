import flet as ft
from database.models import Room, RoomStatus
from database.connection import SessionLocal
from sqlalchemy import cast, Integer
from sqlalchemy.orm import joinedload

class RoomGrid:
    def __init__(self, app_state, on_room_click):
        self.app_state = app_state
        self.on_room_click = on_room_click
        self.grid_container = ft.Column(spacing=15, scroll=ft.ScrollMode.AUTO, expand=True)
        
        # Crear habitaciones por defecto (Rango 2 al 40)
        self.create_default_rooms()
    
    def build(self):
        rooms = self.get_rooms()
        self.grid_container.controls.clear()
        
        # 1. Creamos el Row que contendrá las tarjetas
        grid_layout = ft.Row(
            controls=[self.create_room_card(room) for room in rooms],
            spacing=15,          # Espacio horizontal entre tarjetas
            run_spacing=15,      # Espacio vertical entre filas
            alignment=ft.MainAxisAlignment.CENTER, # <--- CENTRA LAS TARJETAS EN LA FILA
            wrap=True,           # Permite que bajen a la siguiente línea
        )
        
        # 2. Envolvemos el Row en un Container para asegurar que ocupe todo el ancho
        # y permita el centrado real respecto a la pantalla
        centered_content = ft.Container(
            content=grid_layout,
            alignment=ft.alignment.center, # Centra el bloque completo
            padding=ft.padding.all(20),    # Margen interno para que no peguen a los bordes
            expand=True
        )
        
        self.grid_container.controls.append(centered_content)
        return self.grid_container

    def get_rooms(self):
        """Obtiene habitaciones usando strings para evitar errores de importación circular"""
        db = SessionLocal()
        try:
            # Usamos strings "active_stays" y "guests" en lugar de Room.active_stays y Stay.guests
            return db.query(Room).options(
                joinedload("active_stays").joinedload("guests")
            ).order_by(cast(Room.number, Integer)).all()
        except Exception as e:
            print(f"❌ Error en get_rooms: {e}")
            # Fallback por si el joinedload falla: traer solo las habitaciones
            return db.query(Room).order_by(cast(Room.number, Integer)).all()
        finally:
            db.close()
    
    def create_room_card(self, room):
        """Crea la tarjeta visual de la habitación con diseño armónico y profesional"""
        try:
            # 1. Configuración de estilos por estado
            status_configs = {
                RoomStatus.FREE: {
                    "bg": ft.Colors.GREEN_50, "accent": ft.Colors.GREEN_700, 
                    "icon": ft.Icons.BED_OUTLINED, "label": "DISPONIBLE"
                },
                RoomStatus.OCCUPIED: {
                    "bg": ft.Colors.RED_50, "accent": ft.Colors.RED_800, 
                    "icon": ft.Icons.PERSON, "label": "OCUPADA"
                },
                RoomStatus.RESERVED: {
                    "bg": ft.Colors.AMBER_50, "accent": ft.Colors.AMBER_800, 
                    "icon": ft.Icons.EVENT_AVAILABLE, "label": "RESERVADA"
                },
                RoomStatus.CLEANING: {
                    "bg": ft.Colors.CYAN_50, "accent": ft.Colors.CYAN_800, 
                    "icon": ft.Icons.CLEANING_SERVICES, "label": "LIMPIEZA"
                },
                RoomStatus.MAINTENANCE: {
                    "bg": ft.Colors.BLUE_GREY_50, "accent": ft.Colors.BLUE_GREY_800, 
                    "icon": ft.Icons.BUILD_CIRCLE_OUTLINED, "label": "MTTO"
                },
            }
            
            style = status_configs.get(room.status, status_configs[RoomStatus.FREE])
            
            # 2. Lógica de contenido
            guest_name = "---"
            if room.status == RoomStatus.OCCUPIED:
                guest_name = getattr(room, 'current_guest_name', "Huésped Activo")

            return ft.Container(
                width=130,
                height=150,
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1.5, style["accent"] if room.status != RoomStatus.FREE else ft.Colors.GREY_200),
                border_radius=12,
                ink=True,
                on_click=lambda _: self.on_room_click(room),
                
                # --- AGREGANDO SOMBRA PARA VOLUMEN ---
                shadow=ft.BoxShadow(
                    spread_radius=1,
                    blur_radius=3,
                    color=ft.Colors.BLACK12, # Sombra sutil
                    offset=ft.Offset(1, 4),   # Desplazada hacia abajo para dar altura
                ),
                
                # --- EFECTO VISUAL AL PASAR EL MOUSE ---
                on_hover=lambda e: self.on_card_hover(e, style["accent"]),
                
                content=ft.Stack([
                    # Capa de fondo sutil para el estado
                    ft.Container(bgcolor=style["bg"], border_radius=12),
                    
                    # Contenido Principal
                    ft.Column([
                        # Fila superior (Número y Badge de Tipo)
                        ft.Container(
                            padding=ft.padding.only(left=10, right=10, top=10),
                            content=ft.Row([
                                ft.Text(f"{room.number}", size=20, weight=ft.FontWeight.W_800, color=style["accent"]),
                                ft.Container(
                                    content=ft.Text(room.type.upper(), size=7, weight=ft.FontWeight.BOLD, color=ft.Colors.BLACK54),
                                    bgcolor=ft.Colors.with_opacity(0.1, style["accent"]),
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                    border_radius=5
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                        ),
                        
                        # Icono Central
                        ft.Container(
                            expand=True,
                            alignment=ft.alignment.center,
                            content=ft.Column([
                                ft.Icon(style["icon"], color=style["accent"], size=28),
                                ft.Text(
                                    guest_name.upper(), 
                                    size=9, 
                                    weight=ft.FontWeight.BOLD, 
                                    color=ft.Colors.BLACK87,
                                    text_align=ft.TextAlign.CENTER,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS
                                )
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2)
                        ),
                        
                        # Barra de estado inferior
                        ft.Container(
                            width=130,
                            bgcolor=style["accent"],
                            padding=ft.padding.all(4),
                            border_radius=ft.border_radius.only(bottom_left=10, bottom_right=10),
                            content=ft.Text(
                                style["label"], 
                                size=9, 
                                weight=ft.FontWeight.W_700, 
                                color=ft.Colors.WHITE, 
                                text_align=ft.TextAlign.CENTER
                            )
                        )
                    ], spacing=0)
                ])
            )
        except Exception as e:
            print(f"❌ Error en card {room.number}: {e}")
            return ft.Container(width=130, height=150, bgcolor="red", content=ft.Text("Error"))

    def create_default_rooms(self):
        """Crea habitaciones del 2 al 40 si no existen"""
        db = SessionLocal()
        try:
            if db.query(Room).count() > 0:
                return
            
            types = ["Estándar", "Doble", "Suite", "Familiar"]
            for i in range(2, 41):
                room_type = types[i % len(types)]
                new_room = Room(
                    number=str(i),
                    floor=(i // 10) + 1,
                    type=room_type,
                    status=RoomStatus.FREE,
                    base_price_usd=50.0,
                    current_price_usd=50.0,
                    max_occupancy=2,
                    description=f"Habitación {i}"
                )
                db.add(new_room)
            db.commit()
            print("✅ Habitaciones 2-40 creadas")
        except Exception as e:
            print(f"Error: {e}")
            db.rollback()
        finally:
            db.close()


    def on_card_hover(self, e, accent_color):
        """Efecto de elevación cuando el mouse entra en la tarjeta"""
        e.control.shadow = ft.BoxShadow(
            spread_radius=1,
            blur_radius=3,
            color=ft.Colors.with_opacity(0.2, accent_color) if e.data == "true" else ft.Colors.BLACK12,
            offset=ft.Offset(2, 5) if e.data == "true" else ft.Offset(1, 4)
        )
        # Un pequeño zoom al entrar
        e.control.scale = 1.03 if e.data == "true" else 1.0
        e.control.update()