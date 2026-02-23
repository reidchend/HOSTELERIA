import flet as ft
from database.connection import SessionLocal
from database.models import User
from utils.helpers import verify_password

class LoginScreen:
    def __init__(self, page, on_login_success):
        self.page = page
        self.on_login_success = on_login_success
        
        # Campo para mensajes de error (¡IMPORTANTE!)
        self.message = ft.Text(value="", size=14, text_align=ft.TextAlign.CENTER)
        
        self.username = ft.TextField(
            label="Usuario",
            prefix_icon=ft.Icons.PERSON_OUTLINED,
            border_radius=15,
            bgcolor=ft.Colors.WHITE,
            focused_border_color=ft.Colors.BLUE_ACCENT,
            on_submit=self.login # Permite entrar con la tecla Enter
        )
        self.password = ft.TextField(
            label="Contraseña",
            prefix_icon=ft.Icons.LOCK_OUTLINED,
            password=True,
            can_reveal_password=True,
            border_radius=15,
            bgcolor=ft.Colors.WHITE,
            focused_border_color=ft.Colors.BLUE_ACCENT,
            on_submit=self.login
        )

    def build(self):
        # Contenedor con gradiente que ocupa TODO
        return ft.Container(
            content=ft.Column([
                # Tarjeta de Login
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.HOTEL_ROUNDED, size=50, color=ft.Colors.BLUE_ACCENT),
                        ft.Text("Bienvenido", size=30, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                        ft.Text("Inicia sesión para continuar", color=ft.Colors.GREY_600, size=14),
                        
                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        
                        self.username,
                        self.password,
                        
                        # Aquí aparecerá el error
                        self.message, 
                        
                        ft.Divider(height=5, color=ft.Colors.TRANSPARENT),
                        
                        ft.ElevatedButton(
                            text="INGRESAR",
                            style=ft.ButtonStyle(
                                color=ft.Colors.WHITE,
                                bgcolor=ft.Colors.BLUE_ACCENT,
                                shape=ft.RoundedRectangleBorder(radius=12),
                                padding=20,
                            ),
                            width=300,
                            on_click=self.login
                        ),
                    ], 
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15
                    ),
                    bgcolor=ft.Colors.with_opacity(0.9, ft.Colors.WHITE),
                    padding=40,
                    border_radius=30,
                    shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.BLACK26),
                    width=400,
                ),
            ], 
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            # Estas 3 líneas obligan al gradiente a cubrir todo
            expand=True,
            alignment=ft.alignment.center,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[ft.Colors.BLUE_900, ft.Colors.BLUE_400],
            ),
        )

    def login(self, e):
        """Maneja el evento de login"""
        if not self.username.value or not self.password.value:
            self.message.value = "Por favor ingrese credenciales"
            self.message.color = ft.Colors.RED_600
            self.page.update()
            return
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(
                User.username == self.username.value,
                User.is_active == True
            ).first()
            
            if user and verify_password(self.password.value, user.password_hash):
                self.message.value = "¡Acceso concedido!"
                self.message.color = ft.Colors.GREEN_600
                self.page.update()
                
                self.on_login_success({
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "role": user.role.value if hasattr(user.role, 'value') else user.role,
                })
            else:
                self.message.value = "Usuario o contraseña incorrectos"
                self.message.color = ft.Colors.RED_600
                self.page.update()
        except Exception as ex:
            self.message.value = f"Error de conexión: {str(ex)}"
            self.page.update()
        finally:
            db.close()