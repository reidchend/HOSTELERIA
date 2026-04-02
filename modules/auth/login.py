# modules/auth/login.py

import flet as ft
from database.connection import SesionLocal
from database.models import Usuario
from utils.helpers import verificar_contrasena
from utils import handle_error


class PantallaLogin:
    """
    Pantalla de inicio de sesión.
    Muestra un formulario centrado con gradiente de fondo.
    Al autenticarse correctamente, invoca al_iniciar_sesion con los datos del usuario.
    """

    def __init__(self, pagina: ft.Page, al_iniciar_sesion):
        self.pagina           = pagina
        self.al_iniciar_sesion = al_iniciar_sesion

        # Texto de retroalimentación (errores o confirmación)
        self.mensaje = ft.Text(value="", size=14, text_align=ft.TextAlign.CENTER)

        self.campo_usuario = ft.TextField(
            label="Usuario",
            prefix_icon=ft.Icons.PERSON_OUTLINED,
            border_radius=15,
            bgcolor=ft.Colors.WHITE,
            focused_border_color=ft.Colors.BLUE_ACCENT,
            on_submit=self.iniciar_sesion,
        )
        self.campo_contrasena = ft.TextField(
            label="Contraseña",
            prefix_icon=ft.Icons.LOCK_OUTLINED,
            password=True,
            can_reveal_password=True,
            border_radius=15,
            bgcolor=ft.Colors.WHITE,
            focused_border_color=ft.Colors.BLUE_ACCENT,
            on_submit=self.iniciar_sesion,
        )

    def construir(self) -> ft.Container:
        """Construye y retorna el árbol de widgets de la pantalla de login."""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.HOTEL_ROUNDED, size=50, color=ft.Colors.BLUE_ACCENT),
                                ft.Text("Bienvenido", size=30, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLUE_900),
                                ft.Text("Inicia sesión para continuar",
                                        color=ft.Colors.GREY_600, size=14),
                                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                                self.campo_usuario,
                                self.campo_contrasena,
                                self.mensaje,
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
                                    on_click=self.iniciar_sesion,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=15,
                        ),
                        bgcolor=ft.Colors.with_opacity(0.9, ft.Colors.WHITE),
                        padding=40,
                        border_radius=30,
                        shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.BLACK26),
                        width=400,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            alignment=ft.alignment.center,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[ft.Colors.BLUE_900, ft.Colors.BLUE_400],
            ),
        )

    def iniciar_sesion(self, evento):
        """
        Valida las credenciales contra la base de datos.
        Si son correctas, pasa los datos del usuario al callback al_iniciar_sesion.
        """
        if not self.campo_usuario.value or not self.campo_contrasena.value:
            self.mensaje.value = "Por favor ingrese sus credenciales"
            self.mensaje.color = ft.Colors.RED_600
            self.pagina.update()
            return

        sesion = SesionLocal()
        try:
            usuario = sesion.query(Usuario).filter(
                Usuario.nombre_usuario == self.campo_usuario.value,
                Usuario.activo == True
            ).first()

            if usuario and verificar_contrasena(self.campo_contrasena.value, usuario.hash_contrasena):
                self.mensaje.value = "¡Acceso concedido!"
                self.mensaje.color = ft.Colors.GREEN_600
                self.pagina.update()

                # Pasar solo los datos necesarios (no el objeto ORM) para evitar sesiones detached
                self.al_iniciar_sesion({
                    "id":              usuario.id,
                    "nombre_usuario":  usuario.nombre_usuario,
                    "nombre_completo": usuario.nombre_completo,
                    "rol":             usuario.rol.value if hasattr(usuario.rol, 'value') else usuario.rol,
                })
            else:
                self.mensaje.value = "Usuario o contraseña incorrectos"
                self.mensaje.color = ft.Colors.RED_600
                self.pagina.update()

        except Exception as error:
            handle_error(error, self.pagina, "Login")
            self.mensaje.value = f"Error de conexión: {str(error)}"
            self.mensaje.color = ft.Colors.RED_600
            self.pagina.update()
        finally:
            sesion.close()