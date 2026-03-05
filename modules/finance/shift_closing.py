import flet as ft
from database.connection import SessionLocal
from database.models import Shift, Payment, CashDrawer, User
from datetime import datetime

class ShiftClosingDialog:
    def __init__(self, page, shift_id, on_close_complete):
        self.page = page
        self.shift_id = shift_id
        self.on_close_complete = on_close_complete
        
        # 1. Obtener datos del sistema para el cálculo
        self.summary = self.calculate_system_balances()
        
        # 2. Campos de entrada para el conteo físico
        self.physical_main_usd = ft.TextField(
            label="Monto Físico Caja Principal ($)", 
            prefix_text="$ ", value="0", on_change=self.check_differences
        )
        self.physical_petty_usd = ft.TextField(
            label="Monto Físico Caja Chica ($)", 
            prefix_text="$ ", value="0", on_change=self.check_differences
        )
        
        # 3. Etiquetas de diferencia
        self.diff_main_text = ft.Text("Diferencia: $ 0.00", color=ft.Colors.GREY)
        self.diff_petty_text = ft.Text("Diferencia: $ 0.00", color=ft.Colors.GREY)

    def calculate_system_balances(self):
        db = SessionLocal()
        shift = db.get(Shift, self.shift_id)  # SQLAlchemy 2.x: db.get() reemplaza query().get()
        # Sumar pagos de este turno (Caja Principal)
        payments = db.query(Payment).filter(
            Payment.created_at >= shift.start_time,
            Payment.is_refund == False
        ).all()
        # Sumar vueltos por tipo de caja
        refunds_main = db.query(Payment).filter(
            Payment.created_at >= shift.start_time,
            Payment.is_refund == True,
            Payment.description.contains("main")
        ).all()
        refunds_petty = db.query(Payment).filter(
            Payment.created_at >= shift.start_time,
            Payment.is_refund == True,
            Payment.description.contains("petty")
        ).all()
        
        db.close()
        
        total_in = sum(p.amount_usd for p in payments)
        total_out_main = sum(r.amount_usd for r in refunds_main)
        total_out_petty = sum(r.amount_usd for r in refunds_petty)
        
        return {
            "expected_main": total_in - total_out_main,
            "expected_petty": shift.initial_usd - total_out_petty, # Asumiendo initial_usd como fondo de caja chica
        }

    def check_differences(self, _):
        try:
            p_main = float(self.physical_main_usd.value or 0)
            p_petty = float(self.physical_petty_usd.value or 0)
            
            diff_m = p_main - self.summary["expected_main"]
            diff_p = p_petty - self.summary["expected_petty"]
            
            self.diff_main_text.value = f"Diferencia: $ {diff_m:.2f}"
            self.diff_main_text.color = ft.Colors.RED if diff_m < 0 else ft.Colors.GREEN
            
            self.diff_petty_text.value = f"Diferencia: $ {diff_p:.2f}"
            self.diff_petty_text.color = ft.Colors.RED if diff_p < 0 else ft.Colors.GREEN
            
            self.page.update()
        except: pass

    def finalize_shift(self, _):
        db = SessionLocal()
        try:
            shift = db.get(Shift, self.shift_id)  # SQLAlchemy 2.x: db.get() reemplaza query().get()
            shift.end_time = datetime.now()
            shift.final_usd_expected = self.summary["expected_main"]
            shift.final_usd_real = float(self.physical_main_usd.value)
            shift.is_active = False
            
            # Actualizar la caja física en la DB para el siguiente turno
            caja = db.query(CashDrawer).first()
            # La principal se suele retirar (dejar en 0), la chica se mantiene o repone
            caja.main_balance_usd = 0 
            caja.petty_cash_usd = float(self.physical_petty_usd.value)
            
            db.commit()
            self.page.close(self.dialog)
            self.on_close_complete()
            
        except Exception as e:
            db.rollback()
            self.page.open(ft.SnackBar(ft.Text(f"Error: {e}")))  # API correcta en Flet moderno
        finally:
            db.close()

    def show(self):
        self.dialog = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.LOCK), ft.Text("Cierre de Turno")]),
            content=ft.Container(
                width=450,
                content=ft.Column([
                    ft.Text("Resumen del Sistema", weight="bold"),
                    ft.ListTile(
                        title=ft.Text(f"Ventas a Entregar: $ {self.summary['expected_main']:.2f}"),
                        subtitle=ft.Text("Caja Principal (Ventas Netas)"),
                        leading=ft.Icon(ft.Icons.MONETIZATION_ON, color=ft.Colors.GREEN)
                    ),
                    ft.ListTile(
                        title=ft.Text(f"Fondo en Caja Chica: $ {self.summary['expected_petty']:.2f}"),
                        subtitle=ft.Text("Debe permanecer en el hotel"),
                        leading=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.BLUE)
                    ),
                    ft.Divider(),
                    ft.Text("Conteo Físico en Efectivo", weight="bold"),
                    self.physical_main_usd,
                    self.diff_main_text,
                    self.physical_petty_usd,
                    self.diff_petty_text,
                ], tight=True, spacing=10)
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(self.dialog)),
                ft.ElevatedButton("Cerrar Turno y Salir", 
                                 icon=ft.Icons.SAVE_ALT,
                                 bgcolor=ft.Colors.RED_800, color=ft.Colors.WHITE,
                                 on_click=self.finalize_shift)
            ]
        )
        self.page.open(self.dialog)