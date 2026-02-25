import flet as ft
from sqlalchemy import func
from database.connection import init_db, SessionLocal
from database.models import Room, RoomStatus
from modules.auth.login import LoginScreen
from modules.rooms.management import RoomGrid
from modules.rooms.details import RoomDetailsDialog
from utils.helpers import load_config_from_db
from modules.finance.cash_opening import CashOpeningDialog

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
    except Exception as e:
        print(f"Error cargando configuración: {e}")
        config_dict = {}
    finally:
        db_init.close()
    
    # Estado de la aplicación
    app_state = {
        "current_user": None,
        "exchange_rate": float(config_dict.get("exchange_rate", 35.5)),
        "hotel_name": config_dict.get("hotel_name", "Mi Hotel"),
        "selected_room": None,
        "active_view": "dashboard" # 'dashboard' o 'settings'
    }

    # --- Funciones de Lógica de Negocio ---
    
    def update_summary_stats():
        """Obtiene estadísticas de habitaciones en una sola consulta"""
        db = SessionLocal()
        try:
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
        except Exception as e:
            print(f"Error al actualizar estadísticas: {e}")
            return {"total": 0, "free": 0, "occupied": 0, "reserved": 0, "cleaning": 0, "maintenance": 0}
        finally:
            db.close()

    def handle_room_click(room):
        """Maneja el clic en una habitación según su estado"""
        if room.status == RoomStatus.FREE:
            from modules.rooms.checkin import CheckInDialog
            dialog = CheckInDialog(
                page, 
                room, 
                on_success=refresh_view
            )
            dialog.show()
            
        elif room.status == RoomStatus.OCCUPIED:
            details = RoomDetailsDialog(
                page, 
                room, 
                on_checkout_request=handle_checkout_flow
            )
            details.show()

    def handle_checkout_flow(room):
        """Inicia el proceso de check-out"""
        page.open(ft.SnackBar(ft.Text(f"Iniciando proceso de salida para Hab {room.number}...")))

    # --- Funciones de Navegación y Renderizado ---

    def refresh_view():
        """Refresca el contenido de la vista activa"""
        render_app_content()

    def toggle_view(view_name):
        """Cambia entre la vista de dashboard y configuración"""
        app_state["active_view"] = view_name
        render_app_content()

    def load_dashboard(final_rate):
        """Callback tras apertura de caja"""
        app_state["exchange_rate"] = final_rate
        app_state["active_view"] = "dashboard"
        render_app_content()
        print("🚀 Sesión iniciada y Dashboard cargado")

    def logout():
        """Limpia el estado y vuelve al login"""
        app_state["current_user"] = None
        show_login()

    # --- Componentes de Interfaz ---

    def create_summary_cards():
        """Crea las tarjetas informativas superiores"""
        stats = update_summary_stats()
        
        def build_card(label, value, color, subtext):
            return ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text(label, size=12, color=ft.Colors.GREY_700),
                        ft.Text(str(value), size=28, weight=ft.FontWeight.BOLD, color=color),
                        ft.Text(subtext, size=10, color=ft.Colors.GREY_600),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                    padding=10, width=140,
                )
            )

        return ft.Container(
            content=ft.Row([
                build_card("Total", stats["total"], ft.Colors.BLACK, "habitaciones"),
                build_card("Libres", stats["free"], ft.Colors.GREEN, "disponibles"),
                build_card("Ocupadas", stats["occupied"], ft.Colors.RED, "con huéspedes"),
                build_card("Limpieza", stats["cleaning"], ft.Colors.BLUE, "en aseo"),
                build_card("Mantenimiento", stats["maintenance"], ft.Colors.PURPLE, "fuera de servicio"),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=15),
            padding=20,
        )

    def create_top_bar():
        """Crea la barra de navegación superior"""
        user_info = app_state["current_user"]
        user_name = user_info["full_name"] if user_info else "Usuario"

        return ft.Container(
            content=ft.Row([
                # Logo y Nombre
                ft.Row([
                    ft.Icon(ft.Icons.HOTEL, size=32, color=ft.Colors.BLUE_700),
                    ft.Text(app_state["hotel_name"], size=22, weight="bold", color=ft.Colors.BLUE_900),
                ]),
                
                # Acciones y Usuario
                ft.Row([
                    # Botón dinámico según la vista
                    ft.ElevatedButton(
                        text="Dashboard" if app_state["active_view"] == "settings" else "Configuración",
                        icon=ft.Icons.DASHBOARD if app_state["active_view"] == "settings" else ft.Icons.SETTINGS,
                        on_click=lambda _: toggle_view("dashboard" if app_state["active_view"] == "settings" else "settings"),
                        style=ft.ButtonStyle(
                            color=ft.Colors.BLUE_700,
                            bgcolor=ft.Colors.BLUE_50,
                            shape=ft.RoundedRectangleBorder(radius=8)
                        )
                    ),
                    
                    ft.VerticalDivider(width=20),
                    
                    # Tasa de cambio
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ATTACH_MONEY, size=18, color=ft.Colors.GREEN_700),
                            ft.Text(f"Tasa: Bs. {app_state['exchange_rate']:.2f}", size=14, weight="bold"),
                        ]),
                        padding=ft.padding.all(8),
                        bgcolor=ft.Colors.GREEN_50,
                        border_radius=8
                    ),
                    
                    ft.VerticalDivider(width=20),
                    
                    # Perfil de usuario
                    ft.Row([
                        ft.Column([
                            ft.Text(user_name, size=14, weight="bold"),
                            ft.Text(user_info["role"] if user_info else "", size=11, color=ft.Colors.GREY_600),
                        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
                        ft.CircleAvatar(
                            content=ft.Icon(ft.Icons.PERSON),
                            radius=18,
                            bgcolor=ft.Colors.BLUE_GREY_100
                        ),
                        ft.IconButton(
                            icon=ft.Icons.LOGOUT_ROUNDED,
                            icon_color=ft.Colors.RED_400,
                            tooltip="Cerrar Sesión",
                            on_click=lambda _: logout()
                        )
                    ])
                ], spacing=15)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=25, vertical=12),
            bgcolor=ft.Colors.WHITE,
            border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.BLACK12))
        )

    def render_app_content():
        """Función central que dibuja la interfaz principal o configuración"""
        page.clean()
        
        # Header común
        header = create_top_bar()
        
        if app_state["active_view"] == "dashboard":
            # Vista Principal (Mapa de Habitaciones)
            rooms_grid = RoomGrid(app_state, handle_room_click)
            content = ft.Column([
                create_summary_cards(),
                ft.Container(
                    content=rooms_grid.build(), 
                    expand=True, 
                    padding=ft.padding.symmetric(horizontal=30, vertical=10)
                ),
            ], expand=True, spacing=0)
        else:
            # Vista de Configuración / Finanzas
            # Aquí podrías importar tu vista de gestión de caja chica
            from modules.finance.cash_management import CashManagement
            content = CashManagement(page, app_state)

        page.add(
            ft.Column([
                header,
                ft.Container(content=content, expand=True)
            ], expand=True, spacing=0)
        )
        page.update()

    def show_login():
        """Muestra la pantalla de login"""
        page.clean()
        page.padding = 0
        page.spacing = 0
        page.vertical_alignment = ft.MainAxisAlignment.START
        page.horizontal_alignment = ft.CrossAxisAlignment.START
        
        login_screen = LoginScreen(page, on_login_success)
        page.add(login_screen.build())
        page.update()

    def on_login_success(user):
        """Maneja el éxito del login y lanza apertura de caja"""
        app_state["current_user"] = user
        
        opening = CashOpeningDialog(
            page, 
            user, 
            on_complete=load_dashboard 
        )
        opening.show()

    # --- Inicio de la Aplicación ---
    show_login()

if __name__ == "__main__":
    ft.app(target=main)