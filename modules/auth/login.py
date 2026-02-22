# modules/auth/login.py

import flet as ft
from database.connection import SessionLocal
from database.models import User
from utils.helpers import verify_password

class LoginScreen:
    def __init__(self, page, on_login_success):
        self.page = page
        self.on_login_success = on_login_success
        
        # Crear usuario admin por defecto
        self.create_default_admin()
    
    def build(self):
        """Construye y retorna el contenedor del login"""
        self.username = ft.TextField(
            label="Usuario",
            width=300,
            autofocus=True,
            on_submit=self.login
        )
        self.password = ft.TextField(
            label="Contraseña",
            width=300,
            password=True,
            can_reveal_password=True,
            on_submit=self.login
        )
        self.message = ft.Text("", color=ft.Colors.RED)  # Colors con C mayúscula
        
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Icon(ft.Icons.HOTEL, size=80, color=ft.Colors.BLUE),
                    alignment=ft.alignment.center,
                ),
                ft.Text(
                    "Sistema de Gestión Hotelera",
                    size=28,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Iniciar Sesión",
                    size=16,
                    color=ft.Colors.GREY_700,
                ),
                ft.Divider(height=20),
                self.username,
                self.password,
                ft.Row([
                    ft.Checkbox(label="Recordarme", value=False),
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.ElevatedButton(
                    "Ingresar",
                    width=300,
                    height=45,
                    on_click=self.login,
                ),
                self.message,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=30,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=15,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
            ),
            width=400,
        )
    
    def login(self, e):
        """Maneja el evento de login"""
        if not self.username.value or not self.password.value:
            self.message.value = "Por favor ingrese usuario y contraseña"
            self.message.color = ft.Colors.RED
            self.page.update()
            return
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(
                User.username == self.username.value,
                User.is_active == True
            ).first()
            
            if user and verify_password(self.password.value, user.password_hash):
                self.message.value = "¡Bienvenido!"
                self.message.color = ft.Colors.GREEN
                self.page.update()
                
                # Llamar al callback con el usuario
                self.on_login_success({
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "role": user.role.value if hasattr(user.role, 'value') else user.role,
                })
            else:
                self.message.value = "Usuario o contraseña incorrectos"
                self.message.color = ft.Colors.RED
                self.page.update()
        finally:
            db.close()
    
    # modules/auth/login.py - Solo la parte de create_default_admin

    def create_default_admin(self):
        """Crea usuario admin por defecto si no existe"""
        from database.connection import SessionLocal
        from database.models import User, UserRole  # Importar UserRole
        from utils.helpers import hash_password
        
        db = SessionLocal()
        try:
            if db.query(User).count() == 0:
                admin = User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    full_name="Administrador",
                    email="admin@hotel.com",
                    role=UserRole.ADMIN  # Usar el enum, no string
                )
                db.add(admin)
                db.commit()
                print("✅ Usuario admin creado (admin/admin123)")
        except Exception as e:
            print(f"Error creando admin: {e}")
            db.rollback()
        finally:
            db.close()