# main.py

import flet as ft
from database.connection import init_db, SessionLocal
from database.models import Configuration, Room, RoomStatus
from modules.auth.login import LoginScreen
from modules.rooms.management import RoomGrid
from utils.helpers import load_config_from_db

def main(page: ft.Page):
    # Configuración de la página
    page.title = "Hotel Management System"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.window.width = 1400
    page.window.height = 900
    page.window.min_width = 1200
    page.window.min_height = 700
    
    # Inicializar base de datos
    init_db()
    
    # Cargar configuración inicial
    db = SessionLocal()
    try:
        config_dict = load_config_from_db(db)
    finally:
        db.close()
    
    # Estado de la aplicación
    app_state = {
        "current_user": None,
        "exchange_rate": float(config_dict.get("exchange_rate", 35.5)),
        "hotel_name": config_dict.get("hotel_name", "Mi Hotel"),
        "selected_room": None,
    }
    
    def update_summary_stats():
        """Actualiza las estadísticas del resumen"""
        db = SessionLocal()
        try:
            total = db.query(Room).count()
            free = db.query(Room).filter(Room.status == RoomStatus.FREE).count()
            occupied = db.query(Room).filter(Room.status == RoomStatus.OCCUPIED).count()
            reserved = db.query(Room).filter(Room.status == RoomStatus.RESERVED).count()
            cleaning = db.query(Room).filter(Room.status == RoomStatus.CLEANING).count()
            maintenance = db.query(Room).filter(Room.status == RoomStatus.MAINTENANCE).count()
            
            return {
                "total": total,
                "free": free,
                "occupied": occupied,
                "reserved": reserved,
                "cleaning": cleaning,
                "maintenance": maintenance
            }
        finally:
            db.close()
    
    def create_summary_cards():
        """Crea las tarjetas de resumen"""
        stats = update_summary_stats()
        
        return ft.Container(
            content=ft.Row([
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Total", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(stats["total"]), size=28, weight=ft.FontWeight.BOLD),
                            ft.Text("habitaciones", size=10, color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=15,
                        width=120,
                    )
                ),
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Libres", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(stats["free"]), size=28, weight=ft.FontWeight.BOLD, 
                                   color=ft.Colors.GREEN),
                            ft.Text("disponibles", size=10, color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=15,
                        width=120,
                    )
                ),
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Ocupadas", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(stats["occupied"]), size=28, weight=ft.FontWeight.BOLD,
                                   color=ft.Colors.RED),
                            ft.Text("con huéspedes", size=10, color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=15,
                        width=120,
                    )
                ),
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Reservadas", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(stats["reserved"]), size=28, weight=ft.FontWeight.BOLD,
                                   color=ft.Colors.ORANGE),
                            ft.Text("próximas", size=10, color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=15,
                        width=120,
                    )
                ),
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Aseo", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(stats["cleaning"]), size=28, weight=ft.FontWeight.BOLD,
                                   color=ft.Colors.BLUE),
                            ft.Text("en limpieza", size=10, color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=15,
                        width=120,
                    )
                ),
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Mantenimiento", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(stats["maintenance"]), size=28, weight=ft.FontWeight.BOLD,
                                   color=ft.Colors.PURPLE),
                            ft.Text("fuera de servicio", size=10, color=ft.Colors.GREY_600),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=15,
                        width=120,
                    )
                ),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            padding=20,
        )
    
    # Crear la interfaz principal
    def create_main_interface():
        # Barra superior
        top_bar = ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.HOTEL, size=30, color=ft.Colors.BLUE),
                    ft.Text(
                        app_state["hotel_name"],
                        size=20,
                        weight=ft.FontWeight.BOLD,
                    ),
                ]),
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ATTACH_MONEY, size=20),
                            ft.Text(
                                f"Tasa: Bs. {app_state['exchange_rate']:.2f}",
                                size=14,
                            ),
                        ]),
                        padding=10,
                        bgcolor=ft.Colors.BLUE_50,
                        border_radius=5,
                    ),
                    ft.VerticalDivider(width=20),
                    ft.Column([
                        ft.Text(
                            f"Usuario: {app_state['current_user']['full_name'] if app_state['current_user'] else 'No autenticado'}",
                            size=14,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(
                            f"Rol: {app_state['current_user']['role'] if app_state['current_user'] else ''}",
                            size=12,
                            color=ft.Colors.GREY_700,
                        ),
                    ]),
                    ft.IconButton(
                        icon=ft.Icons.LOGOUT,
                        tooltip="Cerrar sesión",
                        on_click=logout,
                    ),
                ]),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=15,
            bgcolor=ft.Colors.WHITE,
            border=ft.border.only(
                bottom=ft.BorderSide(1, ft.Colors.GREY_300)
            ),
        )
        
        # Grid de habitaciones
        rooms_grid = RoomGrid(app_state, on_room_click)
        
        # Contenido completo
        return ft.Column([
            top_bar,
            create_summary_cards(),
            ft.Container(
                content=rooms_grid.build(),
                expand=True,
                padding=20,
            ),
        ], expand=True)
    
    # Manejador de clic en habitación
    def on_room_click(room):
        app_state["selected_room"] = room
        
        # Crear dialog de información
        dialog = ft.AlertDialog(
            title=ft.Text(f"Habitación {room.number}"),
            content=ft.Container(
                content=ft.Column([
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.MEETING_ROOM),
                        title=ft.Text(f"Tipo: {room.type}"),
                    ),
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.INFO),
                        title=ft.Text(f"Estado: {room.status.value if hasattr(room.status, 'value') else room.status}"),
                    ),
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.ATTACH_MONEY),
                        title=ft.Text(f"Precio: ${room.current_price_usd:.2f} / Bs. {room.current_price_usd * app_state['exchange_rate']:.2f}"),
                    ),
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.FLOOR),
                        title=ft.Text(f"Piso: {room.floor}"),
                    ),
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.GROUP),
                        title=ft.Text(f"Capacidad: {room.max_occupancy} personas"),
                    ),
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.SUPPORT_AGENT),
                        title=ft.Text(f"Comodidades: {room.amenities}"),
                    ),
                ]),
                width=400,
                padding=20,
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: close_dialog()),
                ft.ElevatedButton(
                    "Registrar Huésped",
                    icon=ft.Icons.PERSON_ADD,
                    on_click=lambda e: register_guest(room),
                ),
            ],
        )
        
        page.dialog = dialog
        dialog.open = True
        page.update()
    
    def close_dialog():
        page.dialog.open = False
        page.update()
    
    def register_guest(room):
        close_dialog()
        page.show_snack_bar(
            ft.SnackBar(
                content=ft.Text(f"Registro en habitación {room.number} - Módulo en desarrollo"),
                action="OK",
            )
        )
        page.update()
    
    def logout(e):
        app_state["current_user"] = None
        show_login()
    
    def show_login():
        page.clean()
        login_screen = LoginScreen(page, on_login_success)
        page.add(
            ft.Container(
                content=login_screen.build(),
                expand=True,
                alignment=ft.alignment.center,
                bgcolor=ft.Colors.GREY_100,
            )
        )
    
    def on_login_success(user):
        app_state["current_user"] = user
        page.clean()
        page.add(create_main_interface())
        page.update()
    
    # Iniciar con login
    show_login()

if __name__ == "__main__":
    ft.app(target=main)