import flet as ft
from database.connection import SessionLocal
from database.models import ExtraCharge, Stay

class ExtraChargeDialog:
    def __init__(self, page, stay, on_success):
        self.page = page
        self.stay = stay
        self.on_success = on_success
        
        # UI Components
        self.service_name = ft.TextField(label="Servicio", expand=True)
        self.amount_usd = ft.TextField(label="Monto ($)", prefix_text="$ ", width=120)
        
        # Info del Fondo Disponible
        self.fondo_text = ft.Text(
            f"Fondo disponible: $ {stay.deposit_balance_usd:.2f}",
            color=ft.Colors.GREEN_700 if stay.deposit_balance_usd > 0 else ft.Colors.RED_400,
            weight="bold"
        )
        
        self.use_deposit = ft.Switch(
            label="Cobrar del fondo disponible", 
            value=stay.deposit_balance_usd > 0,
            disabled=stay.deposit_balance_usd <= 0
        )

    def save_charge(self, _):
        db = SessionLocal()
        try:
            monto = float(self.amount_usd.value)
            
            # 1. Crear el cargo
            nuevo_cargo = ExtraCharge(
                stay_id=self.stay.id,
                service_name=self.service_name.value,
                amount_usd=monto
            )
            db.add(nuevo_cargo)

            # 2. Si se eligió usar el fondo, descontar
            if self.use_deposit.value:
                # Refrescar stay para evitar inconsistencias
                stay_db = db.query(Stay).get(self.stay.id)
                if stay_db.deposit_balance_usd >= monto:
                    stay_db.deposit_balance_usd -= monto
                    nuevo_cargo.description = "Saldado con fondo a favor"
                else:
                    self.page.show_snack_bar(ft.SnackBar(ft.Text("Fondo insuficiente para cubrir el total")))
                    return

            db.commit()
            self.page.close(self.dialog)
            self.on_success()
        except Exception as e:
            db.rollback()
            self.page.show_snack_bar(ft.SnackBar(ft.Text(f"Error: {e}")))
        finally:
            db.close()

    def show(self):
        self.dialog = ft.AlertDialog(
            title=ft.Text("Cargar Nuevo Consumo"),
            content=ft.Column([
                self.service_name,
                ft.Row([self.amount_usd, self.fondo_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                self.use_deposit
            ], tight=True, spacing=15),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(self.dialog)),
                ft.ElevatedButton("Confirmar", on_click=self.save_charge, bgcolor=ft.Colors.BLUE)
            ]
        )
        self.page.open(self.dialog)