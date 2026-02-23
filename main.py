#main.py

import flet as ft
from sqlalchemy import func
from database.connection import init_db, SessionLocal
from database.models import Room, RoomStatus
from modules.auth.login import LoginScreen
from modules.rooms.management import RoomGrid
from utils.helpers import load_config_from_db

def main(page: ft.Page):
    # --- Configuración de la página ---
    page.title = "Hotel Management System"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    page.window.width = 1400
    page.window.height = 900
    page.window.min_width = 1200
    page.window.min_height = 700
    
    # Inicializar base de datos
    init_db()
    
    # Cargar configuración inicial
    db_init = SessionLocal()
    try:
        config_dict = load_config_from_db(db_init)
    finally:
        db_init.close()
    
    # Estado de la aplicación
    app_state = {
        "current_user": None,
        "exchange_rate": float(config_dict.get("exchange_rate", 35.5)),
        "hotel_name": config_dict.get("hotel_name", "Mi Hotel"),
        "selected_room": None,
    }

    # --- Funciones de Lógica de Negocio ---

    def update_summary_stats():
        """Obtiene estadísticas de habitaciones en una sola consulta (Optimizado)"""
        db = SessionLocal()
        try:
            # Agrupamos por estado y contamos
            results = db.query(Room.status, func.count(Room.id)).group_by(Room.status).all()
            counts = {status: count for status, count in results}
            
            return {
                "total": sum(counts.values()),
                "free": counts.get(RoomStatus.FREE, 0),
                "occupied": counts.get(RoomStatus.OCCUPIED, 0),
                "reserved": counts.get(RoomStatus.RESERVED, 0),
                "cleaning": counts.get(RoomStatus.CLEANING, 0),
                "maintenance": counts.get(RoomStatus.MAINTENANCE, 0)
            }
        finally:
            db.close()

    def handle_room_click(room):
        from modules.rooms.checkin import CheckInDialog
        if room.status == RoomStatus.FREE:
            # Si está libre, abrimos el Check-in
            dialog = CheckInDialog(
                page, 
                room, 
                on_success=refresh_view # Esta función debe recargar tu RoomGrid
            )
            dialog.show()
        elif room.status == RoomStatus.OCCUPIED:
            # Aquí luego haremos el Check-out o ver info
            page.open(ft.SnackBar(ft.Text(f"Habitación ocupada por: {room.current_guest_name}")))

    def create_summary_cards():
        stats = update_summary_stats()
        
        def build_card(label, value, color, subtext):
            return ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text(label, size=12, color=ft.Colors.GREY_700),
                        ft.Text(str(value), size=28, weight=ft.FontWeight.BOLD, color=color),
                        ft.Text(subtext, size=10, color=ft.Colors.GREY_600),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                    padding=10, width=130,
                )
            )

        return ft.Container(
            content=ft.Row([
                build_card("Total", stats["total"], ft.Colors.BLACK, "habitaciones"),
                build_card("Libres", stats["free"], ft.Colors.GREEN, "disponibles"),
                build_card("Ocupadas", stats["occupied"], ft.Colors.RED, "con huéspedes"),
                build_card("Reservadas", stats["reserved"], ft.Colors.ORANGE, "próximas"),
                build_card("Aseo", stats["cleaning"], ft.Colors.BLUE, "en limpieza"),
                build_card("Mantenimiento", stats["maintenance"], ft.Colors.PURPLE, "fuera de servicio"),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            padding=20,
        )

    def create_main_interface():
        # Barra superior (Header)
        top_bar = ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Icon(ft.Icons.HOTEL, size=30, color=ft.Colors.BLUE),
                    ft.Text(app_state["hotel_name"], size=20, weight=ft.FontWeight.BOLD),
                ]),
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ATTACH_MONEY, size=20),
                            ft.Text(f"Tasa: Bs. {app_state['exchange_rate']:.2f}", size=14),
                        ]),
                        padding=10, bgcolor=ft.Colors.BLUE_50, border_radius=5,
                    ),
                    ft.VerticalDivider(width=20),
                    ft.Column([
                        ft.Text(f"Usuario: {app_state['current_user']['full_name'] if app_state['current_user'] else 'Admin'}", size=14, weight=ft.FontWeight.W_500),
                        ft.Text(f"Rol: {app_state['current_user']['role'] if app_state['current_user'] else 'Staff'}", size=12, color=ft.Colors.GREY_700),
                    ], spacing=0),
                    ft.IconButton(icon=ft.Icons.LOGOUT, on_click=lambda _: logout())
                ]),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=15, bgcolor=ft.Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_300)),
        )
        
        rooms_grid = RoomGrid(app_state, handle_room_click)
        
        return ft.Column([
            top_bar,
            create_summary_cards(),
            ft.Container(content=rooms_grid.build(), expand=True, padding=20),
        ], expand=True)

    def refresh_view():
        """Refresca la pantalla completa para mostrar cambios de estado"""
        page.clean()
        page.add(create_main_interface())
        page.update()

    def logout():
        app_state["current_user"] = None
        show_login()

    def show_login():
        page.clean()
        # Reset de la página para que el gradiente mande
        page.padding = 0
        page.spacing = 0
        # Ponemos START para que el hijo (Container expandido) tome todo el control
        page.vertical_alignment = ft.MainAxisAlignment.START
        page.horizontal_alignment = ft.CrossAxisAlignment.START
        
        login_screen = LoginScreen(page, on_login_success)
        
        # Agregamos el login_screen.build() que ahora tiene expand=True
        page.add(login_screen.build())
        page.update()

    def on_login_success(user):
        app_state["current_user"] = user
        print(f"✅ Login exitoso para: {user['full_name']}") # Debug
        
        try:
            page.clean()
            # Resetear visuales para el Dashboard
            page.vertical_alignment = ft.MainAxisAlignment.START
            page.horizontal_alignment = ft.CrossAxisAlignment.START
            page.padding = 0
            
            # Intentar construir la interfaz
            dashboard = create_main_interface()
            page.add(dashboard)
            page.update()
            print("🚀 Dashboard cargado correctamente")
            
        except Exception as e:
            print(f"❌ ERROR CRÍTICO AL CARGAR DASHBOARD: {e}")
            # Mostrar error en pantalla para que no quede en blanco
            page.add(ft.Text(f"Error al cargar la interfaz: {e}", color="red"))
            page.update()
            
    # Inicio de la aplicación
    show_login()

if __name__ == "__main__":
    ft.app(target=main)