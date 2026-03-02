import flet as ft
from database.connection import SessionLocal
from database.models import Payment, CashDrawer, PaymentMethod, Configuration, Stay
from datetime import datetime

class PaymentDialog:
    def __init__(self, page, stay, total_to_pay, on_success):
        self.page = page
        self.stay = stay
        self.total_to_pay = total_to_pay  
        self.on_success = on_success
        self.dialog = None
        self.exchange_rate = 1.0
        self.current_change_usd = 0.0
        
        # --- ESTILO FACTURA: ENCABEZADO DE TOTALES ---
        self.txt_total_usd = ft.Text(f"$ {total_to_pay:.2f}", size=20, weight="bold")
        self.txt_total_bs = ft.Text("", size=16, color="grey700")
        
        # --- ENTRADA DE DATOS (ESTILO FORMULARIO) ---
        self.method_dropdown = ft.Dropdown(
            label="MÉTODO DE PAGO",
            options=[ft.dropdown.Option(key=m.name, text=m.value) for m in PaymentMethod],
            value=PaymentMethod.CASH_USD.name,
            on_change=self.handle_method_change,
            width=200
        )
        
        self.amount_received = ft.TextField(
            label="MONTO RECIBIDO",
            value=f"{total_to_pay:.2f}",
            on_change=self.update_ui,
            width=200,
            suffix_text="USD",
            text_align=ft.TextAlign.RIGHT
        )

        self.reference_field = ft.TextField(
            label="NRO. REFERENCIA",
            visible=False,
            width=200
        )

        # --- DETALLE DE VUELTO (ESTILO TABLA DE FACTURA) ---
        # Definimos los campos de vuelto
        self.v_main_usd = self._create_v_field("Ppal $")
        self.v_petty_usd = self._create_v_field("Chica $")
        self.v_main_bs = self._create_v_field("Ppal Bs")
        self.v_petty_bs = self._create_v_field("Chica Bs")

        self.vuelto_info_text = ft.Text("Vuelto requerido: $ 0.00", weight="bold", color="blue")
        self.vuelto_diff_text = ft.Text("Falta por asignar: $ 0.00", size=12, color="red")

        self.keep_as_credit = ft.Checkbox(label="Abonar excedente a cuenta", value=False, on_change=self.update_ui)

        self.btn_process = ft.ElevatedButton(
            "REGISTRAR PAGO Y CERRAR",
            icon=ft.Icons.RECEIPT_LONG,
            on_click=self.process_payment,
            bgcolor=ft.Colors.BLACK,
            color="white",
            disabled=True,
            height=50
        )

        self.load_initial_data()

    def _create_v_field(self, label):
        return ft.TextField(
            label=label, value="0.00", width=105, 
            text_size=12, on_change=self.validate_mixed_vuelto,
            text_align=ft.TextAlign.RIGHT
        )

    def load_initial_data(self):
        db = SessionLocal()
        try:
            config = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            self.exchange_rate = float(config.value) if config else 1.0
            self.txt_total_bs.value = f"({self.total_to_pay * self.exchange_rate:,.2f} Bs.)"
        finally:
            db.close()
        self.update_ui(None)

    def handle_method_change(self, e):
        method = self.method_dropdown.value
        is_bs = "BS" in method or "PAGO_MOVIL" in method
        self.amount_received.suffix_text = "Bs." if is_bs else "USD"
        self.reference_field.visible = "CASH" not in method
        self.update_ui(e)

    def update_ui(self, e):
        try:
            raw = float(self.amount_received.value or 0)
            is_bs = self.amount_received.suffix_text == "Bs."
            received_usd = raw / self.exchange_rate if is_bs else raw
            
            diff = self.total_to_pay - received_usd
            
            # Reset de estados
            self.btn_process.disabled = True
            
            if diff > 0.01:
                self.vuelto_info_text.value = f"PENDIENTE POR PAGAR: $ {diff:.2f}"
                self.vuelto_info_text.color = "red"
            elif abs(diff) <= 0.01:
                self.vuelto_info_text.value = "PAGO EXACTO"
                self.vuelto_info_text.color = "green"
                self.btn_process.disabled = False
            else:
                self.current_change_usd = abs(diff)
                self.vuelto_info_text.value = f"VUELTO A ENTREGAR: $ {self.current_change_usd:.2f}"
                self.vuelto_info_text.color = "blue"
                if e and e.control == self.amount_received:
                    self.v_main_usd.value = f"{self.current_change_usd:.2f}"
                self.validate_mixed_vuelto(None)

            self.page.update()
        except: pass

    def validate_mixed_vuelto(self, _):
        try:
            v_usd = float(self.v_main_usd.value or 0) + float(self.v_petty_usd.value or 0)
            v_bs = (float(self.v_main_bs.value or 0) + float(self.v_petty_bs.value or 0)) / self.exchange_rate
            
            total_v = v_usd + v_bs
            diff = self.current_change_usd - total_v
            
            if self.keep_as_credit.value:
                self.btn_process.disabled = False
                self.vuelto_diff_text.value = "Se registrará como saldo a favor."
            elif abs(diff) < 0.02:
                self.vuelto_diff_text.value = "✅ Distribución Cuadrada"
                self.vuelto_diff_text.color = "green"
                self.btn_process.disabled = False
            else:
                self.vuelto_diff_text.value = f"❌ Diferencia: $ {diff:.2f}"
                self.vuelto_diff_text.color = "red"
                self.btn_process.disabled = True
        except: pass
        self.page.update()

    def process_payment(self, _):
        db = SessionLocal()
        try:
            method_key = self.method_dropdown.value
            raw_received = float(self.amount_received.value)
            received_usd = raw_received / self.exchange_rate if self.amount_received.suffix_text == "Bs." else raw_received
            
            caja = db.query(CashDrawer).first()
            stay_db = db.query(Stay).get(self.stay.id)

            # 1. Registro de Pago
            db.add(Payment(
                stay_id=self.stay.id, amount_usd=received_usd,
                amount_bs=raw_received if "BS" in method_key else raw_received * self.exchange_rate,
                exchange_rate=self.exchange_rate, method=PaymentMethod[method_key],
                reference=self.reference_field.value or "Efectivo",
                description="Cobro Factura", created_at=datetime.now()
            ))

            # Entrada a Caja
            if "USD" in method_key or "ZELLE" in method_key:
                caja.main_balance_usd += received_usd
            else:
                caja.main_balance_bs += (received_usd * self.exchange_rate)

            # 2. Desglose de Vuelto (Refund)
            if self.current_change_usd > 0.01:
                if self.keep_as_credit.value:
                    stay_db.deposit_balance_usd += self.current_change_usd
                else:
                    vm_usd, vp_usd = float(self.v_main_usd.value or 0), float(self.v_petty_usd.value or 0)
                    vm_bs, vp_bs = float(self.v_main_bs.value or 0), float(self.v_petty_bs.value or 0)

                    # Validaciones
                    if caja.main_balance_usd < vm_usd: raise Exception("Insuficiente en Ppal $")
                    if caja.petty_cash_usd < vp_usd: raise Exception("Insuficiente en Chica $")
                    if caja.main_balance_bs < vm_bs: raise Exception("Insuficiente en Ppal Bs")
                    if caja.petty_cash_bs < vp_bs: raise Exception("Insuficiente en Chica Bs")

                    caja.main_balance_usd -= vm_usd
                    caja.petty_cash_usd -= vp_usd
                    caja.main_balance_bs -= vm_bs
                    caja.petty_cash_bs -= vp_bs

                    db.add(Payment(
                        stay_id=self.stay.id, amount_usd=self.current_change_usd, is_refund=True,
                        method=PaymentMethod[method_key],
                        description=f"Vuelto Mixto Desglosado (Cajas: P$:{vm_usd}/C$:{vp_usd}/PB:{vm_bs}/CB:{vp_bs})"
                    ))

            db.commit()
            self.page.close(self.dialog)
            if self.on_success: self.on_success()
        except Exception as e:
            db.rollback()
            self.page.open(ft.SnackBar(ft.Text(f"ERROR: {str(e)}"), bgcolor="red"))
        finally: db.close()

    def build(self):
        return ft.AlertDialog(
            title=ft.Text("DETALLE DE TRANSACCIÓN / FACTURACIÓN", size=14, weight="bold"),
            content=ft.Container(
                width=480,
                content=ft.Column([
                    ft.Divider(),
                    ft.Row([
                        ft.Column([ft.Text("TOTAL A PAGAR:"), self.txt_total_usd, self.txt_total_bs], spacing=2),
                        ft.VerticalDivider(),
                        ft.Column([self.method_dropdown, self.amount_received, self.reference_field], spacing=10)
                    ], height=160),
                    ft.Divider(),
                    ft.Column([
                        self.vuelto_info_text,
                        ft.Text("DISTRIBUCIÓN DE CAJAS (EGRESO):", size=11, weight="bold"),
                        ft.Row([self.v_main_usd, self.v_petty_usd, self.v_main_bs, self.v_petty_bs], spacing=5),
                        self.vuelto_diff_text,
                        self.keep_as_credit
                    ], spacing=10),
                ], tight=True)
            ),
            actions=[self.btn_process],
            actions_alignment=ft.MainAxisAlignment.CENTER,
            shape=ft.RoundedRectangleBorder(radius=5)
        )

    def show(self):
        self.dialog = self.build()
        self.page.open(self.dialog)