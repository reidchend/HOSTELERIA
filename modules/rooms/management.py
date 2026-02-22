# modules/rooms/management.py

import flet as ft
from database.models import Room, RoomStatus
from database.connection import SessionLocal

class RoomGrid:
    def __init__(self, app_state, on_room_click):
        self.app_state = app_state
        self.on_room_click = on_room_click
        self.grid_container = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO)
        
        # Crear habitaciones por defecto si no existen
        self.create_default_rooms()
    
    def build(self):
        """Construye y retorna el grid de habitaciones"""
        # Obtener habitaciones de la base de datos
        rooms = self.get_rooms()
        
        # Limpiar el contenedor
        self.grid_container.controls.clear()
        
        # Crear grid de 39 habitaciones (3 filas de 13)
        for i in range(0, len(rooms), 13):
            row_rooms = rooms[i:i+13]
            row = ft.Row(
                [self.create_room_card(room) for room in row_rooms],
                spacing=5,
                alignment=ft.MainAxisAlignment.CENTER,
                wrap=True,
            )
            self.grid_container.controls.append(row)
        
        return self.grid_container
    
    def create_room_card(self, room):
        """Crea una tarjeta para una habitación"""
        # Mapeo de colores según estado
        status_colors = {
            RoomStatus.FREE: {"bg": ft.Colors.GREEN_100, "border": ft.Colors.GREEN, "text": "LIBRE"},
            RoomStatus.OCCUPIED: {"bg": ft.Colors.RED_100, "border": ft.Colors.RED, "text": "OCUPADA"},
            RoomStatus.RESERVED: {"bg": ft.Colors.ORANGE_100, "border": ft.Colors.ORANGE, "text": "RESERVADA"},
            RoomStatus.CLEANING: {"bg": ft.Colors.BLUE_100, "border": ft.Colors.BLUE, "text": "ASEO"},
            RoomStatus.MAINTENANCE: {"bg": ft.Colors.PURPLE_100, "border": ft.Colors.PURPLE, "text": "MTTO"},
        }
        
        colors = status_colors.get(room.status, status_colors[RoomStatus.FREE])
        
        # Calcular precio en bolívares
        exchange_rate = float(self.app_state.get("exchange_rate", 35.5))
        price_ves = room.current_price_usd * exchange_rate
        
        return ft.Container(
            content=ft.Column([
                ft.Text(f"#{room.number}", size=14, weight=ft.FontWeight.BOLD),
                ft.Text(room.type, size=10, color=ft.Colors.GREY_700),
                ft.Text(f"${room.current_price_usd:.0f}", size=12, weight=ft.FontWeight.BOLD),
                ft.Text(f"Bs. {price_ves:.0f}", size=10),
                ft.Container(
                    content=ft.Text(colors["text"], size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    bgcolor=colors["border"],
                    padding=ft.padding.only(left=5, right=5, top=2, bottom=2),
                    border_radius=3,
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
            width=95,
            height=130,
            padding=8,
            bgcolor=colors["bg"],
            border=ft.border.all(2, colors["border"]),
            border_radius=8,
            ink=True,
            on_click=lambda e, r=room: self.on_room_click(r),
        )
    
    def get_rooms(self):
        """Obtiene las habitaciones de la base de datos"""
        db = SessionLocal()
        try:
            rooms = db.query(Room).order_by(Room.number).all()
            return rooms
        finally:
            db.close()
    
    def create_default_rooms(self):
        """Crea 39 habitaciones por defecto si no existen"""
        db = SessionLocal()
        try:
            # Verificar si ya existen habitaciones
            if db.query(Room).count() > 0:
                return
            
            # Tipos de habitación para variedad
            types = ["Estándar", "Doble", "Suite", "Familiar"]
            
            # Crear 39 habitaciones
            for i in range(1, 40):
                room_type = types[(i - 1) % len(types)]
                
                # Precios según tipo
                if room_type == "Suite":
                    price = 120.0
                elif room_type == "Familiar":
                    price = 90.0
                elif room_type == "Doble":
                    price = 70.0
                else:
                    price = 50.0
                
                # Estado inicial: algunas ocupadas para demostración
                if i % 5 == 0:
                    status = RoomStatus.OCCUPIED
                elif i % 7 == 0:
                    status = RoomStatus.RESERVED
                elif i % 9 == 0:
                    status = RoomStatus.CLEANING
                elif i % 11 == 0:
                    status = RoomStatus.MAINTENANCE
                else:
                    status = RoomStatus.FREE
                
                room = Room(
                    number=f"{i:03d}",
                    floor=(i - 1) // 13 + 1,
                    type=room_type,
                    status=status,
                    base_price_usd=price,
                    current_price_usd=price,
                    max_occupancy=4 if room_type == "Familiar" else 2,
                    description=f"Habitación {room_type} en piso {(i - 1) // 13 + 1}",
                    amenities="WiFi, TV, A/A" if i % 3 == 0 else "WiFi, TV",
                )
                db.add(room)
            
            db.commit()
            print("✅ 39 habitaciones creadas por defecto")
        finally:
            db.close()