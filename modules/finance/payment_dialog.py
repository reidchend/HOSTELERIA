import flet as ft
from database.connection import SessionLocal
from database.models import Payment, CashDrawer, PaymentMethod, Configuration
from datetime import datetime

class PaymentDialog:
    def __init__(self, page, stay, total_to_pay, on_success):
        self.page = page
        self.stay = stay
        self.total_to_pay = total_to_pay  # Monto total en USD pendiente
        self.on_success = on_success
        self.dialog = None
        self.exchange_rate = 1.0
        
        # --- CAMPOS DE ENTRADA ---
        self.amount_received_usd = ft.TextField(
            label="Monto Recibido ($)", 
            value=f"{total_to_pay:.2f}",
            on_change=self.update_ui,
            expand=True,
            prefix_icon=ft.Icons.ATTACH_MONEY
        )
        
        self.method_dropdown = ft.Dropdown(
            label="Método de Pago",
            options=[ft.dropdown.Option(key=m.name, text=m.value) for m in PaymentMethod],
            value=PaymentMethod.CASH_USD.name,
            expand=True,
            on_change=self.handle_method_change
        )

        self.reference_field = ft.TextField(
            label="Referencia / Confirmación",
            hint_text="Nro de transferencia o Zelle",
            visible=False,
            expand=True
        )

        # --- OPCIÓN DE SALDO A FAVOR ---
        self.keep_as_credit = ft.Checkbox(
            label="Dejar excedente como saldo a favor",
            value=False,
            on_change=self.update_ui,
            visible=False
        )
        
        # --- CONSOLA DE FACTURACIÓN (DESGLOSE) ---
        self.billing_details = ft.Column(spacing=2)
        self.billing_console = ft.Container(
            content=ft.Column([
                ft.Text("CONSOLA DE FACTURACIÓN", size=12, weight="bold", color=ft.Colors.BLUE_GREY_400),
                self.billing_details,
            ]),
            padding=15,
            bgcolor=ft.Colors.BLACK,
            border_radius=8,
            border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
        )

        # --- INFO DE VUELTO ---
        self.origin_vuelto_label = ft.Text("Origen del vuelto:", size=14, weight="bold", visible=False)
        self.origin_vuelto = ft.RadioGroup(
            content=ft.Row([
                ft.Radio(value="main", label="Caja Principal"),
                ft.Radio(value="petty", label="Caja Chica"),
            ]), 
            value="main",
            visible=False
        )

        # Cargar tasa inicial
        self.load_initial_data()

    def load_initial_data(self):
        db = SessionLocal()
        self.exchange_rate = self.get_exchange_rate(db)
        db.close()
        self.refresh_billing_details()

    def get_exchange_rate(self, db):
        """Usa 'exchange_rate' para consistencia con CashManagement"""
        config = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
        if config and config.value:
            try:
                return float(config.value)
            except ValueError:
                return 1.0
        return 1.0

    def handle_method_change(self, e):
        is_cash = "CASH" in self.method_dropdown.value
        self.reference_field.visible = not is_cash
        self.update_ui(e)

    def update_ui(self, _):
        self.refresh_billing_details()
        self.page.update()

    def refresh_billing_details(self):
        try:
            received = float(self.amount_received_usd.value or 0)
            total_bs = self.total_to_pay * self.exchange_rate
            received_bs = received * self.exchange_rate
            change_usd = max(0, received - self.total_to_pay)
            change_bs = change_usd * self.exchange_rate
            
            # Visibilidad de controles según excedente
            has_change = change_usd > 0.001
            self.keep_as_credit.visible = has_change
            
            # Si se marca "Saldo a favor", ocultamos el selector de origen de vuelto
            is_credit = self.keep_as_credit.value and has_change
            self.origin_vuelto.visible = has_change and not is_credit
            self.origin_vuelto_label.visible = has_change and not is_credit

            status_text = "SALDO A FAVOR:" if is_credit else "VUELTO:"
            status_color = ft.Colors.AMBER_400 if is_credit else (ft.Colors.GREEN_400 if has_change else ft.Colors.BLUE_GREY_400)

            # Construir visual de la consola
            self.billing_details.controls = [
                self._console_row("SUBTOTAL:", f"$ {self.total_to_pay:.2f}", f"Bs. {total_bs:,.2f}"),
                self._console_row("RECIBIDO:", f"$ {received:.2f}", f"Bs. {received_bs:,.2f}", ft.Colors.BLUE_400),
                ft.Divider(color=ft.Colors.BLUE_GREY_800, height=10),
                self._console_row(status_text, f"$ {change_usd:.2f}", f"Bs. {change_bs:,.2f}", status_color),
                ft.Text(f"TASA APLICADA: 1$ = {self.exchange_rate:,.2f} BS", size=10, color=ft.Colors.BLUE_GREY_500, italic=True)
            ]
        except ValueError:
            pass

    def _console_row(self, label, val_usd, val_bs, color=ft.Colors.WHITE):
        return ft.Row([
            ft.Text(label, size=11, color=ft.Colors.BLUE_GREY_200, width=100),
            ft.Text(val_usd, size=13, weight="bold", color=color, expand=True),
            ft.Text(val_bs, size=13, weight="bold", color=color),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    def process_payment(self, _):
        if not self.amount_received_usd.value: return

        db = SessionLocal()
        try:
            received = float(self.amount_received_usd.value)
            change = received - self.total_to_pay
            is_credit = self.keep_as_credit.value and change > 0.001
            
            # 1. Obtener o inicializar Caja
            caja = db.query(CashDrawer).first()
            if not caja:
                caja = CashDrawer(main_balance_usd=0, main_balance_bs=0, petty_cash_usd=0)
                db.add(caja)

            # 2. Registrar el Ingreso Total
            selected_method = PaymentMethod[self.method_dropdown.value]
            
            new_payment = Payment(
                stay_id=self.stay.id,
                amount_usd=received,
                exchange_rate=self.exchange_rate,
                method=selected_method,
                reference=self.reference_field.value if self.reference_field.visible else "Efectivo",
                description="Cobro de estadía / Consumos",
                is_refund=False
            )
            db.add(new_payment)
            
            # 3. Actualizar Saldo de Caja (Entra el dinero completo)
            if selected_method == PaymentMethod.CASH_USD:
                caja.main_balance_usd += received
            elif selected_method == PaymentMethod.CASH_BS:
                caja.main_balance_bs += (received * self.exchange_rate)
            
            # 4. Manejo de Vuelto o Saldo a Favor
            if change > 0.001:
                if is_credit:
                    # Si es saldo a favor, simplemente NO registramos el egreso (Refund)
                    # El pago de 'received' ya cubre la deuda y deja el excedente en la cuenta de la estadía
                    pass
                else:
                    # Si es Vuelto físico, registramos el egreso de caja y el movimiento de devolución
                    if self.origin_vuelto.value == "main":
                        if caja.main_balance_usd < change:
                            raise Exception("Caja Principal sin fondo suficiente para el vuelto.")
                        caja.main_balance_usd -= change
                    else:
                        if caja.petty_cash_usd < change:
                            raise Exception("Caja Chica sin fondo suficiente para el vuelto.")
                        caja.petty_cash_usd -= change
                    
                    # Registrar el egreso (Refund) para que el balance de la estadía quede en 0
                    refund = Payment(
                        stay_id=self.stay.id,
                        amount_usd=change,
                        exchange_rate=self.exchange_rate,
                        method=selected_method,
                        is_refund=True,
                        description=f"Vuelto entregado al huésped desde {self.origin_vuelto.value}"
                    )
                    db.add(refund)

            caja.last_update = datetime.now()
            db.commit()
            
            self.page.close(self.dialog)
            msg = "Pago procesado y excedente acreditado" if is_credit else "Pago y vuelto procesados"
            self.page.open(ft.SnackBar(ft.Text(f"✅ {msg}"), bgcolor="green"))
            
            if self.on_success: self.on_success()
            
        except Exception as e:
            db.rollback()
            self.page.open(ft.SnackBar(ft.Text(f"❌ Error: {str(e)}"), bgcolor="red"))
        finally:
            db.close()

    def build(self):
        return ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.RECEIPT_LONG, color="blue"), ft.Text("Facturación y Pago")]),
            content=ft.Container(
                width=450,
                content=ft.Column([
                    self.billing_console,
                    ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                    ft.Text("Entrada de Pago", weight="bold", size=14),
                    self.method_dropdown,
                    self.reference_field,
                    self.amount_received_usd,
                    self.keep_as_credit,
                    ft.Column([
                        self.origin_vuelto_label,
                        self.origin_vuelto
                    ], spacing=5),
                ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO)
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(self.dialog)),
                ft.ElevatedButton(
                    "Procesar Transacción", 
                    icon=ft.Icons.CHECK_CIRCLE,
                    on_click=self.process_payment, 
                    bgcolor=ft.Colors.BLUE_800, 
                    color=ft.Colors.WHITE
                )
            ]
        )

    def show(self):
        self.dialog = self.build()
        self.page.open(self.dialog)