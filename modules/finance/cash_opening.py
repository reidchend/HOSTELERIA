# modules/finance/cash_opening.py
import flet as ft
from database.connection import SessionLocal
from database.models import CashDrawer, Configuration, Shift

class CashOpeningDialog:
    def __init__(self, page, user, on_complete):
        self.page = page
        self.user = user
        self.on_complete = on_complete
        
        # Cargar datos actuales de la DB
        db = SessionLocal()
        self.caja = db.query(CashDrawer).first()
        tasa_cfg = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
        self.current_tasa = float(tasa_cfg.value) if tasa_cfg else 0.0
        db.close()

        # Fields
        self.usd_field = ft.TextField(
            label="Efectivo USD en Caja", 
            value=f"{self.caja.main_balance_usd:.2f}", 
            prefix_text="$ ", expand=True
        )
        self.bs_field = ft.TextField(
            label="Efectivo Bs en Caja", 
            value=f"{self.caja.main_balance_bs:.2f}", 
            prefix_text="Bs ", expand=True
        )
        self.tasa_field = ft.TextField(
            label="Tasa de Cambio Hoy", 
            value=f"{self.current_tasa:.2f}", 
            expand=True
        )

    def confirm_opening(self, _):
        db = SessionLocal()
        try:
            # 1. Crear el nuevo turno
            nuevo_turno = Shift(
                user_id=self.user['id'],
                initial_usd=float(self.usd_field.value),
                initial_bs=float(self.bs_field.value),
                initial_exchange_rate=float(self.tasa_field.value),
                is_active=True
            )
            db.add(nuevo_turno)
            
            # 2. Actualizar la tasa en la configuración global
            tasa_cfg = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            if tasa_cfg:
                tasa_cfg.value = self.tasa_field.value
            
            db.commit()
            
            # Guardamos el ID del turno en el estado de la aplicación
            self.page.session.set("current_shift_id", nuevo_turno.id)
            
            self.page.close(self.dialog)
            self.on_complete(float(self.tasa_field.value))
            
        except Exception as e:
            db.rollback()
            self.page.show_snack_bar(ft.SnackBar(ft.Text(f"Error al abrir turno: {e}")))
        finally:
            db.close()

    def show(self):
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.LOCK_OPEN), ft.Text("Apertura de Turno")]),
            content=ft.Container(
                width=400,
                content=ft.Column([
                    ft.Text(f"Bienvenido/a, {self.user['full_name']}", weight="bold", size=18),
                    ft.Text("Verifique los montos en físico antes de iniciar:", color=ft.Colors.GREY_700),
                    ft.Divider(),
                    ft.Row([self.usd_field, self.bs_field]),
                    self.tasa_field,
                    ft.Text("Al confirmar, se registrará el inicio de su jornada laboral.", 
                            size=12, italic=True, color=ft.Colors.BLUE_GREY_400)
                ], tight=True, spacing=15)
            ),
            actions=[
                ft.ElevatedButton("Confirmar y Entrar", 
                                 icon=ft.Icons.CHECK, 
                                 on_click=self.confirm_opening,
                                 bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE)
            ]
        )
        self.page.open(self.dialog)
