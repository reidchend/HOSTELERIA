import flet as ft
from datetime import datetime, timedelta
from sqlalchemy.orm import selectinload
from database.connection import SessionLocal
from database.models import Room, Stay, Payment, Configuration, CashDrawer, PaymentMethod
from modules.finance.payment_dialog import PaymentDialog

class RoomDetailsDialog:
    def __init__(self, page, room, on_checkout_request):
        self.page = page
        self.room = room
        self.on_checkout_request = on_checkout_request
        self.dialog = None
        self.stay = None

    def get_exchange_rate(self, db):
        config = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
        if config and config.value:
            try:
                return float(config.value)
            except ValueError:
                return 1.0
        return 1.0

    def build(self):
        db = SessionLocal()
        try:
            room_data = db.query(Room).filter(Room.id == self.room.id).options(
                selectinload(Room.active_stays).selectinload(Stay.guests),
                selectinload(Room.active_stays).selectinload(Stay.extra_charges),
                selectinload(Room.active_stays).selectinload(Stay.payments)
            ).first()
            
            if not room_data or not room_data.active_stays:
                return ft.AlertDialog(title=ft.Text("Error"), content=ft.Text("No se encontró información."))

            active_stay = next((s for s in room_data.active_stays if s.is_active), None)
            if not active_stay:
                return ft.AlertDialog(title=ft.Text("Aviso"), content=ft.Text("No hay una estadía activa."))

            self.stay = active_stay 
            exchange_rate = self.get_exchange_rate(db)

            # --- CÁLCULOS ---
            titular = active_stay.guests[0] if active_stay.guests else None
            acompanantes = active_stay.guests[1:] if len(active_stay.guests) > 1 else []
            
            delta = (active_stay.check_out.date() - active_stay.check_in.date()).days
            dias_estadia = max(1, delta)
            
            subtotal_hab = dias_estadia * self.room.base_price_usd
            total_extras = sum(c.amount_usd for c in active_stay.extra_charges)
            pagado_usd = sum(p.amount_usd if not p.is_refund else -p.amount_usd for p in active_stay.payments)
            
            total_cuenta_usd = subtotal_hab + total_extras
            saldo_pendiente_usd = total_cuenta_usd - pagado_usd
            
            es_credito = saldo_pendiente_usd < -0.01
            color_saldo = ft.Colors.GREEN_700 if es_credito else (ft.Colors.RED_700 if saldo_pendiente_usd > 0.01 else ft.Colors.BLUE_GREY_700)
            label_saldo = "Saldo a Favor:" if es_credito else "Saldo Pendiente:"

            # --- INTERFAZ ---
            layout = ft.Column([
                # Bloque Tiempos
                ft.Container(
                    content=ft.Row([
                        self._info_item("Entrada", active_stay.check_in.strftime("%d/%m/%Y")),
                        ft.VerticalDivider(),
                        self._info_item("Salida Prevista", active_stay.check_out.strftime("%d/%m/%Y")),
                        ft.VerticalDivider(),
                        ft.Column([
                            ft.Text("Días", size=11, color=ft.Colors.BLUE_GREY_400),
                            ft.Row([
                                ft.Text(str(dias_estadia), weight="bold", size=14, color=ft.Colors.BLUE),
                                ft.IconButton(ft.Icons.AUTORENEW, icon_size=16, on_click=self.open_renew_dialog, tooltip="Añadir días/Renovar")
                            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER)
                        ], expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ], height=50),
                    bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=10
                ),

                # Información del Titular
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.PERSON, color=ft.Colors.BLUE_800),
                            ft.Column([
                                ft.Text(titular.full_name if titular else "N/A", weight="bold", size=16),
                                ft.Text(f"Titular - Doc: {titular.document_id if titular else 'S/D'}", size=12),
                            ], spacing=0)
                        ]),
                    ]),
                    padding=ft.padding.only(bottom=5)
                ),

                # Sección de Acompañantes
                ft.ExpansionTile(
                    title=ft.Text(f"Acompañantes ({len(acompanantes)})", size=13, weight="bold"),
                    leading=ft.Icon(ft.Icons.GROUP_OUTLINED, size=20),
                    initially_expanded=False,
                    controls=[
                        ft.ListTile(
                            dense=True,
                            title=ft.Text(ac.full_name, size=13),
                            subtitle=ft.Text(f"Doc: {ac.document_id}", size=11),
                            leading=ft.Icon(ft.Icons.SUBDIRECTORY_ARROW_RIGHT, size=16)
                        ) for ac in acompanantes
                    ] if acompanantes else [
                        ft.Container(
                            content=ft.Text("Sin acompañantes registrados", size=12, italic=True),
                            padding=10
                        )
                    ]
                ),

                # Bloque Financiero
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("Estado de Cuenta:", size=14, weight="bold"),
                            ft.Column([
                                ft.Text(f"{label_saldo} ${abs(saldo_pendiente_usd):.2f}", size=18, weight="bold", color=color_saldo),
                                ft.Text(f"Bs. {abs(saldo_pendiente_usd * exchange_rate):,.2f}", size=12, color=color_saldo),
                            ], horizontal_alignment=ft.CrossAxisAlignment.END),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        
                        ft.Row([
                            ft.ElevatedButton("Cargo Extra", icon=ft.Icons.ADD_SHOPPING_CART, on_click=self.add_extra_charge_click, expand=True),
                            ft.ElevatedButton(
                                "Ir a Pagar", icon=ft.Icons.PAYMENTS, bgcolor=ft.Colors.GREEN_700, color="white",
                                on_click=lambda _: self.open_payment_module(saldo_pendiente_usd), expand=True,
                                visible=saldo_pendiente_usd > 0.01
                            ),
                            ft.ElevatedButton(
                                "Entregar Vuelto", icon=ft.Icons.MONEY_OFF, bgcolor=ft.Colors.ORANGE_800, color="white",
                                on_click=lambda _: self.open_refund_selector(abs(saldo_pendiente_usd)), expand=True,
                                visible=es_credito
                            ),
                        ], spacing=10)
                    ]),
                    padding=15, bgcolor=ft.Colors.GREY_100, border_radius=12
                ),

                ft.Text("Resumen de Consumos", weight="bold", size=14),
                self._build_consumos_table(active_stay)
            ], scroll=ft.ScrollMode.AUTO, tight=True, spacing=15)

            self.dialog = ft.AlertDialog(
                title=ft.Row([ft.Icon(ft.Icons.BED, color="red"), ft.Text(f"Habitación {self.room.number}")]),
                content=ft.Container(content=layout, width=550),
                actions=[
                    ft.TextButton("Cerrar", on_click=lambda _: self.page.close(self.dialog)),
                    ft.ElevatedButton(
                        "Check-Out Final", icon=ft.Icons.EXIT_TO_APP, bgcolor="red", color="white",
                        on_click=lambda _: self.on_checkout_request(self.room),
                        disabled=saldo_pendiente_usd > 0.01
                    ),
                ]
            )
            return self.dialog
        finally:
            db.close()

    def _info_item(self, label, value, color=ft.Colors.BLACK):
        return ft.Column([
            ft.Text(label, size=11, color=ft.Colors.BLUE_GREY_400),
            ft.Text(value, weight="bold", size=14, color=color),
        ], expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def _build_consumos_table(self, stay):
        rows = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("Hospedaje Base")),
                ft.DataCell(ft.Text(f"$ {self.room.base_price_usd:.2f} (x d)"))
            ])
        ]
        for charge in stay.extra_charges:
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(charge.service_name)),
                ft.DataCell(ft.Text(f"$ {charge.amount_usd:.2f}"))
            ]))

        if not stay.extra_charges and not stay.payments:
            return ft.Text("No hay cargos adicionales.", size=12, italic=True)

        return ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Concepto")), ft.DataColumn(ft.Text("Monto USD"))],
            rows=rows
        )

    # --- LÓGICA DE RENOVACIÓN ---
    def open_renew_dialog(self, _):
        days_input = ft.TextField(label="Días a renovar", value="1", suffix_text="noche(s)", keyboard_type=ft.KeyboardType.NUMBER)
        
        def confirm_renewal(_):
            try:
                days = int(days_input.value)
                if days <= 0: return
                db = SessionLocal()
                stay = db.query(Stay).filter(Stay.id == self.stay.id).first()
                stay.check_out = stay.check_out + timedelta(days=days)
                db.commit()
                db.close()
                self.page.close(renew_modal)
                self.refresh_details()
                self.page.open(ft.SnackBar(ft.Text(f"Estadía extendida {days} día(s).")))
            except: pass

        renew_modal = ft.AlertDialog(
            title=ft.Text("Renovar Estadía"),
            content=days_input,
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(renew_modal)),
                ft.ElevatedButton("Confirmar", on_click=confirm_renewal)
            ]
        )
        self.page.open(renew_modal)

    # --- LÓGICA DE ENTREGA DE VUELTO ---
    def open_refund_selector(self, amount):
        source_radio = ft.RadioGroup(content=ft.Column([
            ft.Radio(value="main", label="Caja Principal (Efectivo)"),
            ft.Radio(value="small", label="Caja Chica (Recepción)"),
            ft.Radio(value="admin_pm", label="Pago Móvil (Desde Administración)"),
        ]))
        source_radio.value = "main"

        def process_refund(e):
            db = SessionLocal()
            try:
                source = source_radio.value
                caja = db.query(CashDrawer).first()
                description = ""
                method = PaymentMethod.CASH_USD

                if source == "main":
                    if caja.main_balance_usd < amount: raise Exception("Caja Principal sin fondos.")
                    caja.main_balance_usd -= amount
                    description = "Vuelto devuelto desde Caja Principal"
                elif source == "small":
                    if caja.small_cash_usd < amount: raise Exception("Caja Chica sin fondos.")
                    caja.small_cash_usd -= amount
                    description = "Vuelto devuelto desde Caja Chica"
                elif source == "admin_pm":
                    method = PaymentMethod.TRANSFER 
                    description = "Vuelto devuelto vía Pago Móvil Administrador"

                refund_entry = Payment(
                    stay_id=self.stay.id, amount_usd=amount,
                    exchange_rate=self.get_exchange_rate(db),
                    method=method, is_refund=True, description=description
                )
                db.add(refund_entry); db.commit()
                self.page.close(refund_modal); self.refresh_details()
                self.page.open(ft.SnackBar(ft.Text("Vuelto entregado exitosamente"), bgcolor="green"))
            except Exception as ex:
                self.page.open(ft.SnackBar(ft.Text(str(ex)), bgcolor="red"))
            finally:
                db.close()

        refund_modal = ft.AlertDialog(
            title=ft.Text("Seleccionar Origen del Vuelto"),
            content=ft.Column([ft.Text(f"Monto: ${amount:.2f}"), source_radio], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(refund_modal)),
                ft.ElevatedButton("Procesar", on_click=process_refund, bgcolor="orange", color="white")
            ]
        )
        self.page.open(refund_modal)

    def open_payment_module(self, amount):
        self.page.close(self.dialog)
        pay_dialog = PaymentDialog(self.page, self.stay, total_to_pay=amount, on_success=self.refresh_details)
        pay_dialog.show()

    def add_extra_charge_click(self, _):
        from modules.finance.extra_charges import ExtraChargeDialog
        dialog = ExtraChargeDialog(self.page, self.stay, on_success=self.refresh_details)
        dialog.show()

    def refresh_details(self):
        self.show()

    def show(self):
        self.dialog = self.build()
        self.page.open(self.dialog)