import flet as ft
from database.connection import SessionLocal
from database.models import CashDrawer, Configuration
from datetime import datetime

class CashManagement(ft.Container):
    def __init__(self, page, app_state):
        super().__init__()
        self.page = page
        self.app_state = app_state
        self.expand = True
        self.padding = 30
        self.init_ui()

    def get_cash_data(self):
        db = SessionLocal()
        try:
            # Traemos la caja chica y la tasa de cambio
            caja = db.query(CashDrawer).first()
            tasa = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            return caja, tasa
        except Exception as e:
            print(f"Error al obtener datos financieros: {e}")
            return None, None
        finally:
            db.close()

    def update_rate(self, new_value):
        try:
            val_float = float(new_value)
            db = SessionLocal()
            tasa = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            if tasa:
                tasa.value = str(val_float)
                db.commit()
                # Actualizamos el estado global de la app para que el main.py se entere
                self.app_state["exchange_rate"] = val_float
                
                self.page.open(ft.SnackBar(
                    ft.Text(f"✅ Tasa actualizada a {val_float} Bs."),
                    bgcolor=ft.Colors.GREEN_700
                ))
            db.close()
            self.refresh_ui()
        except ValueError:
            self.page.open(ft.SnackBar(ft.Text("❌ Por favor ingrese un número válido")))

    def handle_cash_movement(self, is_income):
        """Abre un diálogo para registrar ingresos o egresos"""
        title = "Nuevo Ingreso" if is_income else "Nuevo Egreso/Gasto"
        color = ft.Colors.GREEN if is_income else ft.Colors.RED
        
        amount_input = ft.TextField(label="Monto", prefix_text="$ ", keyboard_type=ft.KeyboardType.NUMBER)
        description_input = ft.TextField(label="Concepto / Motivo", multiline=True)
        currency_selector = ft.Dropdown(
            label="Moneda",
            options=[
                ft.dropdown.Option("USD", "Dólares ($)"),
                ft.dropdown.Option("BS", "Bolívares (Bs)"),
            ],
            value="USD"
        )

        def save_movement(e):
            if not amount_input.value or float(amount_input.value) <= 0:
                amount_input.error_text = "Monto requerido"
                amount_input.update()
                return

            db = SessionLocal()
            try:
                caja = db.query(CashDrawer).first()
                amount = float(amount_input.value)
                
                if currency_selector.value == "USD":
                    if is_income:
                        caja.main_balance_usd += amount
                    else:
                        if caja.main_balance_usd < amount:
                            self.page.open(ft.SnackBar(ft.Text("Saldo insuficiente en USD")))
                            return
                        caja.main_balance_usd -= amount
                else:
                    if is_income:
                        caja.main_balance_bs += amount
                    else:
                        if caja.main_balance_bs < amount:
                            self.page.open(ft.SnackBar(ft.Text("Saldo insuficiente en Bs")))
                            return
                        caja.main_balance_bs -= amount
                
                db.commit()
                self.page.close(dialog)
                self.page.open(ft.SnackBar(ft.Text("✅ Movimiento registrado correctamente"), bgcolor=ft.Colors.GREEN_800))
                self.refresh_ui()
            except Exception as ex:
                print(f"Error: {ex}")
            finally:
                db.close()

        dialog = ft.AlertDialog(
            title=ft.Text(title, color=color),
            content=ft.Column([
                ft.Text("Complete los datos del movimiento:"),
                amount_input,
                currency_selector,
                description_input
            ], tight=True, spacing=15),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(dialog)),
                ft.ElevatedButton("Guardar", bgcolor=color, color=ft.Colors.WHITE, on_click=save_movement)
            ]
        )
        self.page.open(dialog)

    def init_ui(self):
        caja, tasa = self.get_cash_data()
        
        # Si no hay datos, mostramos error
        if not caja:
            self.content = ft.Text("No se pudo cargar la información de la caja.")
            return

        # Componente de Tasa de Cambio
        self.rate_input = ft.TextField(
            label="Tasa USD/BS",
            value=tasa.value if tasa else "0.00",
            width=150,
            suffix_text="Bs",
            text_align=ft.TextAlign.RIGHT,
            border_color=ft.Colors.BLUE_400
        )

        # Tarjetas de Saldo
        self.card_usd = self.create_balance_card("Saldo Dólares", f"$ {caja.main_balance_usd:.2f}", ft.Colors.GREEN_700, ft.Icons.ATTACH_MONEY)
        self.card_bs = self.create_balance_card("Saldo Bolívares", f"Bs {caja.main_balance_bs:.2f}", ft.Colors.BLUE_700, ft.Icons.MONEY)

        self.content = ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("Gestión de Caja y Finanzas", size=32, weight="bold", color=ft.Colors.BLUE_900),
                    ft.Text("Administra la tasa de cambio y movimientos de caja chica", size=14, color=ft.Colors.GREY_600),
                ], spacing=2),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            
            ft.Container(height=20), # Espaciador alternativo
            
            # FILA SUPERIOR: Saldos y Tasa
            ft.Row([
                self.card_usd,
                self.card_bs,
                ft.Container(
                    content=ft.Column([
                        ft.Text("Tasa del Día", weight="bold", color=ft.Colors.WHITE),
                        self.rate_input,
                        ft.ElevatedButton(
                            "Actualizar Tasa", 
                            icon=ft.Icons.REFRESH, 
                            on_click=lambda _: self.update_rate(self.rate_input.value),
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.BLUE_700,
                                color=ft.Colors.WHITE
                            )
                        )
                    ], spacing=10),
                    padding=20, 
                    bgcolor=ft.Colors.BLUE_GREY_800, 
                    border_radius=15,
                    width=250,
                    height=180
                )
            ], alignment=ft.MainAxisAlignment.START, spacing=25),

            ft.Divider(height=40),
            
            # FILA INFERIOR: Botones de Ajuste
            ft.Text("Operaciones de Caja Chica", size=18, weight="bold"),
            ft.Row([
                ft.ElevatedButton(
                    "Ingreso Manual", 
                    icon=ft.Icons.ADD_CIRCLE, 
                    bgcolor=ft.Colors.GREEN_50, 
                    color=ft.Colors.GREEN_900,
                    height=50,
                    on_click=lambda _: self.handle_cash_movement(is_income=True)
                ),
                ft.ElevatedButton(
                    "Salida / Gasto", 
                    icon=ft.Icons.REMOVE_CIRCLE, 
                    bgcolor=ft.Colors.RED_50, 
                    color=ft.Colors.RED_900,
                    height=50,
                    on_click=lambda _: self.handle_cash_movement(is_income=False)
                ),
            ], spacing=20)
        ], scroll=ft.ScrollMode.AUTO, expand=True)

    def create_balance_card(self, title, amount, color, icon):
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(icon, size=24, color=color),
                    ft.Text(title, size=14, color=ft.Colors.GREY_700, weight="w500"),
                ], alignment=ft.MainAxisAlignment.START, spacing=10),
                ft.Text(amount, size=30, weight="bold", color=color),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=15),
            width=280,
            height=180,
            bgcolor=ft.Colors.WHITE,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=15,
            padding=25,
            shadow=ft.BoxShadow(
                blur_radius=15, 
                color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                offset=ft.Offset(0, 5)
            )
        )

    def refresh_ui(self):
        """Vuelve a cargar los datos y redibuja la interfaz interna"""
        caja, tasa = self.get_cash_data()
        if caja and tasa:
            # Actualizamos los labels directamente navegando por los controles
            self.card_usd.content.controls[1].value = f"$ {caja.main_balance_usd:.2f}"
            self.card_bs.content.controls[1].value = f"Bs {caja.main_balance_bs:.2f}"
            self.rate_input.value = tasa.value
            self.update()
            self.page.update()