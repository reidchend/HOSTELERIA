import flet as ft
from database.connection import SessionLocal
from database.models import (
    Payment, CashDrawer, PaymentMethod, Configuration,
    Stay, Guest, Room
)
from datetime import datetime

# ─────────────────────────────────────────────────────────
# Configuración visual centralizada por método de pago.
# Cada método tiene su color, ícono y si opera en Bs o USD.
# ─────────────────────────────────────────────────────────
METHOD_CONFIG = {
    PaymentMethod.CASH_USD: {
        "label": "Efectivo $",
        "icon":  ft.Icons.ATTACH_MONEY,
        "color": ft.Colors.GREEN_800,
        "is_bs": False,
    },
    PaymentMethod.CASH_BS: {
        "label": "Efectivo Bs",
        "icon":  ft.Icons.MONEY,
        "color": ft.Colors.TEAL_700,
        "is_bs": True,
    },
    PaymentMethod.TRANSFER_BS: {
        "label": "Transferencia",
        "icon":  ft.Icons.SWAP_HORIZ,
        "color": ft.Colors.BLUE_700,
        "is_bs": True,
    },
    PaymentMethod.PAGO_MOVIL: {
        "label": "Pago Móvil",
        "icon":  ft.Icons.PHONE_ANDROID,
        "color": ft.Colors.PURPLE_700,
        "is_bs": True,
    },
    PaymentMethod.ZELLE: {
        "label": "Zelle",
        "icon":  ft.Icons.SEND,
        "color": ft.Colors.INDIGO_700,
        "is_bs": False,
    },
    PaymentMethod.DEBIT_CARD: {
        "label": "T. Débito",
        "icon":  ft.Icons.CREDIT_CARD,
        "color": ft.Colors.ORANGE_700,
        "is_bs": False,
    },
}


class PaymentDialog:
    """
    Diálogo de cobro con dos paneles en paralelo:

      IZQUIERDO ── Factura detallada del folio con saldo dinámico.
                   Se actualiza en tiempo real con cada pago añadido.

      DERECHO ──── Área operativa: métodos de pago, formulario de entrada,
                   lista de pagos de la sesión y sección de sobrante/vuelto.

    Flujo principal:
      1. El recepcionista pulsa un método de pago → aparece el formulario.
      2. Ingresa el monto → pulsa "AGREGAR PAGO".
      3. El pago aparece en la lista y el saldo se actualiza al instante.
      4. Puede agregar más pagos (diferentes métodos) hasta cubrir el total.
      5. Si el cliente paga de más, aparece la sección de sobrante con dos opciones:
           a) Dejar como saldo a favor (queda asociado al huésped, persiste entre estadías).
           b) Entregar vuelto en efectivo con desglose multimoneda/multicaja.
      6. Al finalizar se graba todo en la BD en una sola transacción atómica.
    """

    def __init__(self, page: ft.Page, stay, total_to_pay: float, on_success):
        self.page         = page
        self.stay         = stay
        self.stay_id      = stay.id        # Guardamos el ID; el objeto puede estar detached
        self.total_to_pay = total_to_pay   # Saldo neto pendiente al abrir el diálogo
        self.on_success   = on_success
        self.dialog       = None

        # ── Estado de la sesión de cobro ──────────────────────────────────
        # Lista de pagos añadidos ESTA sesión (aún no grabados en BD).
        # Cada elemento es un dict con los campos necesarios para Payment.
        self.session_payments: list = []
        self.exchange_rate: float   = 1.0
        self.tax_rate: float        = 0.0

        # ── Referencias a widgets dinámicos ───────────────────────────────
        # Mantener referencias directas evita tener que reconstruir
        # todo el árbol de widgets con cada actualización.
        self._balance_col    = ft.Column(spacing=6)   # Saldo en el panel izquierdo
        self._payments_col   = ft.Column(spacing=6)   # Lista de pagos de la sesión
        self._input_area     = ft.Column(spacing=8)   # Formulario del método activo
        self._change_section = ft.Container(visible=False)  # Sobrante / vuelto
        self.btn_finalize    = None                   # Se instancia en build()

        # Referencias para el procesamiento de sobrante
        self._credit_radio   = None   # RadioGroup (crédito vs vuelto)
        self._change_fields  = None   # Tupla de 4 TextFields de desglose de vuelto
        self._change_usd     = 0.0    # Monto de sobrante calculado

        self._load_config()

    # ═══════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS
    # ═══════════════════════════════════════════════════════════════════════

    def _load_config(self):
        """Lee tasa de cambio e IVA desde la tabla de configuración."""
        db = SessionLocal()
        try:
            rate = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            tax  = db.query(Configuration).filter(Configuration.key == "tax_percentage").first()
            self.exchange_rate = float(rate.value) if rate else 1.0
            self.tax_rate = float(tax.value)  if tax  else 0.0
        finally:
            db.close()

    def _get_invoice_data(self, db) -> dict:
        """
        Carga el folio completo desde la BD (siempre fresco para evitar
        objetos detached de SQLAlchemy).
        """
        from sqlalchemy.orm import selectinload

        stay = (
            db.query(Stay)
            .options(
                selectinload(Stay.guests),
                selectinload(Stay.extra_charges),
                selectinload(Stay.payments),
            )
            .filter(Stay.id == self.stay_id)
            .first()
        )
        room = db.query(Room).filter(Room.id == stay.room_id).first()

        # ── Líneas del folio ─────────────────────────────────────────────
        nights     = max(1, (stay.check_out.date() - stay.check_in.date()).days)
        price_unit = room.current_price_usd or room.base_price_usd

        line_items = [
            {
                "concept": f"Hospedaje — Hab. {room.number} "
                           f"({nights} noche{'s' if nights > 1 else ''})",
                "qty":   nights,
                "unit":  price_unit,
                "total": nights * price_unit,
            }
        ]
        for c in stay.extra_charges:
            qty = max(c.quantity, 1)
            line_items.append({
                "concept": c.service_name,
                "qty":     qty,
                "unit":    c.amount_usd / qty,
                "total":   c.amount_usd,
            })

        subtotal = sum(i["total"] for i in line_items)
        tax      = round(subtotal * (self.tax_rate / 100), 2)
        total    = subtotal + tax

        # ── Pagos ya grabados en BD (sesiones anteriores) ────────────────
        prev_payments = [p for p in stay.payments if not p.is_refund]

        return {
            "stay":          stay,
            "room":          room,
            "line_items":    line_items,
            "subtotal":      subtotal,
            "tax":           tax,
            "total":         total,
            "prev_payments": prev_payments,
            "titular":       stay.guests[0] if stay.guests else None,
            "check_in_str":  stay.check_in.strftime("%d/%m/%Y"),
            "check_out_str": stay.check_out.strftime("%d/%m/%Y"),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # CÁLCULO DE SALDO EN TIEMPO REAL
    # ═══════════════════════════════════════════════════════════════════════

    def _calc_remaining(self) -> float:
        """
        Retorna el saldo pendiente en USD.
          > 0  → el cliente aún debe dinero
          ≈ 0  → cuenta saldada exactamente
          < 0  → el cliente pagó de más (sobrante)
        total_to_pay ya descuenta los pagos previos grabados en BD.
        """
        session_paid = sum(p["amount_usd"] for p in self.session_payments)
        tax      = round(self.total_to_pay * (self.tax_rate / 100), 2)

        return self.total_to_pay - session_paid + tax

    # ═══════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN PRINCIPAL DE LA UI
    # ═══════════════════════════════════════════════════════════════════════

    def build(self):
        db = SessionLocal()
        try:
            inv = self._get_invoice_data(db)
        finally:
            db.close()

        # Botón de finalizar (necesario antes de construir los paneles)
        self.btn_finalize = ft.ElevatedButton(
            text="FINALIZAR COBRO",
            icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
            bgcolor=ft.Colors.GREY_400,
            color=ft.Colors.WHITE,
            disabled=True,
            on_click=self._finalize_payment,
            height=46,
        )

        left_panel  = self._build_invoice_panel(inv)
        right_panel = self._build_payment_panel()

        content = ft.Row(
            controls=[
                # Panel izquierdo: Factura con fondo gris muy suave
                ft.Container(
                    content=left_panel,
                    width=310,
                    bgcolor=ft.Colors.GREY_50,
                    border=ft.border.only(right=ft.border.BorderSide(1, ft.Colors.GREY_200)),
                    padding=18,
                ),
                # Panel derecho: Área de cobro
                ft.Container(
                    content=right_panel,
                    expand=True,
                    padding=18,
                ),
            ],
            spacing=0,
            expand=True,
        )

        self.dialog = ft.AlertDialog(
            title=self._build_title(inv),
            content=ft.Container(content=content, width=860, height=530),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(self.dialog)),
                self.btn_finalize,
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        return self.dialog

    # ── Encabezado del diálogo ─────────────────────────────────────────────

    def _build_title(self, inv) -> ft.Row:
        titular = inv["titular"]
        return ft.Row(
            controls=[
                ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE_800, size=22),
                ft.Column(
                    controls=[
                        ft.Text(f"Factura — Habitación {inv['room'].number}",
                                weight="bold", size=15),
                        ft.Text(
                            titular.full_name if titular else "Huésped",
                            size=11, color=ft.Colors.GREY_600
                        ),
                    ],
                    spacing=1,
                ),
                ft.Container(expand=True),
                # Tasa de cambio siempre visible en el encabezado
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.CURRENCY_EXCHANGE, size=13, color=ft.Colors.GREY_600),
                            ft.Text(f"Tasa: Bs. {self.exchange_rate:,.2f}",
                                    size=12, color=ft.Colors.GREY_700),
                        ],
                        spacing=5,
                    ),
                    bgcolor=ft.Colors.GREY_100,
                    padding=ft.padding.symmetric(horizontal=12, vertical=5),
                    border_radius=20,
                ),
            ],
            spacing=10,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PANEL IZQUIERDO — FACTURA
    # ═══════════════════════════════════════════════════════════════════════

    def _build_invoice_panel(self, inv) -> ft.Column:
        """
        Construye la columna izquierda con el folio completo.
        La parte inferior (_balance_col) se actualiza dinámicamente.
        """
        # ── Filas de consumos ────────────────────────────────────────────
        item_rows = []
        for item in inv["line_items"]:
            item_rows.append(
                ft.Row(
                    controls=[
                        ft.Text(item["concept"], size=11, expand=4, color=ft.Colors.BLACK87),
                        ft.Text(
                            f"x{item['qty']}", size=10, expand=1,
                            color=ft.Colors.GREY_600,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            f"${item['total']:.2f}", size=11, expand=2,
                            text_align=ft.TextAlign.RIGHT,
                            weight="bold",
                        ),
                    ],
                )
            )

        # ── Pagos previos (ya en BD) ─────────────────────────────────────
        prev_rows = []
        for p in inv["prev_payments"]:
            prev_rows.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.CHECK, size=11, color=ft.Colors.GREEN_700),
                        ft.Text(p.method.value, size=10, expand=True, color=ft.Colors.GREEN_700),
                        ft.Text(f"-${p.amount_usd:.2f}", size=10,
                                color=ft.Colors.GREEN_700, text_align=ft.TextAlign.RIGHT),
                    ],
                )
            )

        # Inicializar el bloque de saldo dinámico
        self._balance_col.controls = self._make_balance_rows()

        # ── Bloque de fechas ─────────────────────────────────────────────
        dates_row = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("Entrada", size=9, color=ft.Colors.GREY_500),
                        ft.Text(inv["check_in_str"], size=11, weight="bold"),
                    ],
                    spacing=1,
                ),
                ft.Container(expand=True),
                ft.Column(
                    controls=[
                        ft.Text("Salida", size=9, color=ft.Colors.GREY_500),
                        ft.Text(inv["check_out_str"], size=11, weight="bold"),
                    ],
                    spacing=1,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
            ],
        )

        # ── Construcción del contenedor de factura ───────────────────────
        invoice_body = ft.Column(
            controls=[
                dates_row,
                ft.Divider(height=1, color=ft.Colors.GREY_300),

                # Cabecera de la tabla
                ft.Row(
                    controls=[
                        ft.Text("Concepto", size=9, weight="bold",
                                color=ft.Colors.GREY_500, expand=4),
                        ft.Text("Cant", size=9, weight="bold",
                                color=ft.Colors.GREY_500, expand=1,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text("Total", size=9, weight="bold",
                                color=ft.Colors.GREY_500, expand=2,
                                text_align=ft.TextAlign.RIGHT),
                    ],
                ),
                ft.Column(controls=item_rows, spacing=7),
                ft.Divider(height=1, color=ft.Colors.GREY_300),

                # Subtotal / IVA
                ft.Row(
                    controls=[
                        ft.Text("Subtotal:", size=11, expand=True, color=ft.Colors.GREY_700),
                        ft.Text(f"${inv['subtotal']:.2f}", size=11, text_align=ft.TextAlign.RIGHT),
                    ],
                ),
                ft.Row(
                    controls=[
                        ft.Text(f"IVA ({self.tax_rate:.0f}%):", size=11,
                                expand=True, color=ft.Colors.GREY_700),
                        ft.Text(f"${inv['tax']:.2f}", size=11, text_align=ft.TextAlign.RIGHT),
                    ],
                ),

                # TOTAL con equivalente en Bs
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text("TOTAL:", size=13, weight="bold", expand=True),
                            ft.Column(
                                controls=[
                                    ft.Text(f"${inv['total']:.2f}", size=17,
                                            weight="bold", color=ft.Colors.BLUE_900),
                                    ft.Text(
                                        f"Bs. {inv['total'] * self.exchange_rate:,.2f}",
                                        size=10, color=ft.Colors.GREY_600,
                                        text_align=ft.TextAlign.RIGHT,
                                    ),
                                ],
                                spacing=1,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                    ),
                    bgcolor=ft.Colors.BLUE_50,
                    padding=10,
                    border_radius=8,
                ),

                # Pagos previos (si los hay)
                *(
                    [ft.Divider(height=1), ft.Column(controls=prev_rows, spacing=4)]
                    if prev_rows else []
                ),

                ft.Divider(height=1, color=ft.Colors.GREY_300),

                # ── Saldo dinámico (se refresca en cada pago añadido) ──
                self._balance_col,
            ],
            spacing=8,
        )

        return ft.Column(
            controls=[
                ft.Text("DETALLE DEL FOLIO", size=9, weight="bold",
                        color=ft.Colors.BLUE_GREY_400),
                ft.Container(
                    content=invoice_body,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=10,
                    border=ft.border.all(1, ft.Colors.GREY_200),
                    padding=14,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )

    def _make_balance_rows(self) -> list:
        """
        Genera las filas del bloque de saldo.
        Se llama cada vez que session_payments cambia.
        """
        remaining    = self._calc_remaining()
        session_paid = sum(p["amount_usd"] for p in self.session_payments)
        rows         = []

        # ── Abonado en esta sesión ───────────────────────────────────────
        if self.session_payments:
            rows.append(
                ft.Row(
                    controls=[
                        ft.Text("Abonado ahora:", size=11, expand=True,
                                color=ft.Colors.GREEN_700),
                        ft.Column(
                            controls=[
                                ft.Text(f"${session_paid:.2f}", size=12, weight="bold",
                                        color=ft.Colors.GREEN_700,
                                        text_align=ft.TextAlign.RIGHT),
                                ft.Text(
                                    f"Bs. {session_paid * self.exchange_rate:,.2f}",
                                    size=10, color=ft.Colors.GREEN_600,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ],
                            spacing=1,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                        ),
                    ],
                )
            )

        # ── Pendiente / Saldado / Sobrante ───────────────────────────────
        if remaining > 0.01:
            rows.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.PENDING, color=ft.Colors.RED_700, size=15),
                                    ft.Text("PENDIENTE:", size=12, weight="bold",
                                            color=ft.Colors.RED_700, expand=True),
                                    ft.Text(f"${remaining:.2f}", size=15,
                                            weight="bold", color=ft.Colors.RED_700),
                                ],
                            ),
                            ft.Text(
                                f"Bs. {remaining * self.exchange_rate:,.2f}",
                                size=11, color=ft.Colors.RED_400,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                        ],
                        spacing=3,
                    ),
                    bgcolor=ft.Colors.RED_50,
                    padding=10,
                    border_radius=8,
                )
            )
        elif remaining < -0.01:
            sobrante = abs(remaining)
            rows.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.ARROW_CIRCLE_UP,
                                            color=ft.Colors.ORANGE_700, size=15),
                                    ft.Text("SOBRANTE:", size=12, weight="bold",
                                            color=ft.Colors.ORANGE_700, expand=True),
                                    ft.Text(f"${sobrante:.2f}", size=15,
                                            weight="bold", color=ft.Colors.ORANGE_700),
                                ],
                            ),
                            ft.Text(
                                f"Bs. {sobrante * self.exchange_rate:,.2f}",
                                size=11, color=ft.Colors.ORANGE_400,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                        ],
                        spacing=3,
                    ),
                    bgcolor=ft.Colors.ORANGE_50,
                    padding=10,
                    border_radius=8,
                )
            )
        else:
            # Cuenta exactamente saldada
            rows.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700, size=16),
                            ft.Text("CUENTA SALDADA", size=12, weight="bold",
                                    color=ft.Colors.GREEN_700),
                        ],
                        spacing=6,
                    ),
                    bgcolor=ft.Colors.GREEN_50,
                    padding=10,
                    border_radius=8,
                )
            )

        return rows

    # ═══════════════════════════════════════════════════════════════════════
    # PANEL DERECHO — OPERATIVA DE COBRO
    # ═══════════════════════════════════════════════════════════════════════

    def _build_payment_panel(self) -> ft.Column:
        """
        Construye la columna derecha con métodos de pago, formulario
        activo, lista de pagos y sección de sobrante.
        """
        # Placeholder inicial del área de ingreso
        self._input_area.controls = [
            ft.Container(
                content=ft.Text(
                    "← Selecciona un método para ingresar el pago",
                    size=12, color=ft.Colors.GREY_500, italic=True,
                ),
                padding=ft.padding.symmetric(vertical=12),
            )
        ]

        # Botones de métodos de pago
        method_buttons = []
        for method, cfg in METHOD_CONFIG.items():
            method_buttons.append(
                ft.ElevatedButton(
                    text=cfg["label"],
                    icon=cfg["icon"],
                    style=ft.ButtonStyle(
                        color=cfg["color"],
                        bgcolor=ft.Colors.with_opacity(0.07, cfg["color"]),
                        shape=ft.RoundedRectangleBorder(radius=8),
                        side=ft.BorderSide(1.2, ft.Colors.with_opacity(0.3, cfg["color"])),
                    ),
                    height=42,
                    on_click=lambda _, m=method: self._select_method(m),
                )
            )

        return ft.Column(
            controls=[
                ft.Text("MÉTODO DE PAGO", size=9, weight="bold",
                        color=ft.Colors.BLUE_GREY_400),
                ft.Row(controls=method_buttons, wrap=True, spacing=8, run_spacing=8),
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                self._input_area,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.RECEIPT, size=13, color=ft.Colors.BLUE_GREY_300),
                        ft.Text("PAGOS DE ESTA SESIÓN", size=9, weight="bold",
                                color=ft.Colors.BLUE_GREY_300),
                    ],
                    spacing=5,
                ),
                self._payments_col,
                self._change_section,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # LÓGICA DE INTERACCIÓN
    # ═══════════════════════════════════════════════════════════════════════

    def _select_method(self, method: PaymentMethod):
        """
        Muestra el formulario de entrada adaptado al método seleccionado.
        Sugiere automáticamente el saldo pendiente como monto.
        """
        self.selected_method = method
        cfg    = METHOD_CONFIG[method]
        is_bs  = cfg["is_bs"]
        needs_ref = method not in [PaymentMethod.CASH_USD, PaymentMethod.CASH_BS]

        # ── Monto sugerido: el pendiente actual ──────────────────────────
        remaining = self._calc_remaining()
        if remaining > 0:
            suggested = (
                f"{remaining * self.exchange_rate:.2f}" if is_bs
                else f"{remaining:.2f}"
            )
        else:
            suggested = "0.00"

        amount_field = ft.TextField(
            label=f"Monto recibido ({'Bs.' if is_bs else 'USD'})",
            value=suggested,
            suffix_text="Bs." if is_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
            autofocus=True,
            expand=True,
        )
        ref_field = ft.TextField(
            label="Nro. Referencia / Confirmación",
            visible=needs_ref,
            expand=True,
        )

        def add_this_payment(_):
            """Valida e incorpora el pago a la lista de sesión."""
            try:
                raw = float(amount_field.value.replace(",", ".") or 0)
                if raw <= 0:
                    amount_field.error_text = "Ingrese un monto válido"
                    amount_field.update()
                    return
                amount_field.error_text = None

                amount_usd = raw / self.exchange_rate if is_bs else raw
                amount_bs  = raw if is_bs else raw * self.exchange_rate

                self.session_payments.append({
                    "method":     method,
                    "amount_usd": amount_usd,
                    "amount_bs":  amount_bs,
                    "reference":  ref_field.value.strip() if needs_ref else "",
                    "label":      cfg["label"],
                    "color":      cfg["color"],
                    "icon":       cfg["icon"],
                    # Cadena legible para mostrar en la lista
                    "display":    f"Bs. {raw:,.2f}" if is_bs else f"${raw:.2f}",
                })
                self._refresh_ui()

            except (ValueError, AttributeError):
                amount_field.error_text = "Número inválido"
                amount_field.update()

        # Construir la fila de campos según si necesita referencia o no
        input_row = [amount_field, ref_field] if needs_ref else [amount_field]

        self._input_area.controls = [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Icon(cfg["icon"], color=cfg["color"], size=18),
                                ft.Text(cfg["label"], weight="bold",
                                        color=cfg["color"], size=13),
                            ],
                            spacing=6,
                        ),
                        ft.Row(controls=input_row, spacing=10),
                        ft.ElevatedButton(
                            "+ AGREGAR PAGO",
                            bgcolor=cfg["color"],
                            color=ft.Colors.WHITE,
                            on_click=add_this_payment,
                            expand=True,
                            height=40,
                        ),
                    ],
                    spacing=10,
                ),
                padding=14,
                bgcolor=ft.Colors.with_opacity(0.04, cfg["color"]),
                border_radius=10,
                border=ft.border.all(1.5, ft.Colors.with_opacity(0.25, cfg["color"])),
            )
        ]
        self.page.update()

    def _refresh_ui(self):
        """
        Actualiza todos los widgets dinámicos tras cualquier cambio en
        self.session_payments. Este es el único punto desde donde
        se deben actualizar la factura y el panel de cobro para
        mantener consistencia.
        """
        # 1. Actualizar saldo en el panel izquierdo
        self._balance_col.controls = self._make_balance_rows()

        # 2. Reconstruir la lista de pagos de la sesión
        self._payments_col.controls = []
        for i, p in enumerate(self.session_payments):
            self._payments_col.controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(p["icon"], size=14, color=p["color"]),
                            ft.Text(p["label"], size=12, expand=True),
                            ft.Text(p["display"], size=12, weight="bold"),
                            ft.Text(f"  (${p['amount_usd']:.2f})",
                                    size=10, color=ft.Colors.GREY_600),
                            ft.IconButton(
                                ft.Icons.REMOVE_CIRCLE_OUTLINE,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Quitar este pago",
                                on_click=lambda _, idx=i: self._remove_payment(idx),
                            ),
                        ],
                        spacing=4,
                    ),
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    bgcolor=ft.Colors.with_opacity(0.06, p["color"]),
                    border_radius=7,
                )
            )

        # 3. Evaluar el saldo y configurar el botón de finalizar
        remaining = self._calc_remaining()

        if remaining < -0.01:
            # Hay sobrante: mostrar opciones de vuelto/crédito
            self._show_change_section(abs(remaining))
            self.btn_finalize.disabled = False
            self.btn_finalize.bgcolor  = ft.Colors.ORANGE_700
            self.btn_finalize.text     = "CONFIRMAR Y GESTIONAR SOBRANTE"
        elif abs(remaining) <= 0.01 and self.session_payments:
            # Pago exacto
            self._change_section.visible = False
            self.btn_finalize.disabled   = False
            self.btn_finalize.bgcolor    = ft.Colors.GREEN_700
            self.btn_finalize.text       = "FINALIZAR COBRO"
        else:
            # Aún falta por cubrir
            self._change_section.visible = False
            self.btn_finalize.disabled   = True
            self.btn_finalize.bgcolor    = ft.Colors.GREY_400
            self.btn_finalize.text       = "FINALIZAR COBRO"

        self.page.update()

    def _remove_payment(self, index: int):
        """Elimina un pago de la sesión actual y refresca la UI."""
        self.session_payments.pop(index)
        self._refresh_ui()

    def _show_change_section(self, change_usd: float):
        """
        Construye y muestra la sección de sobrante.
        Ofrece dos modos:
          - Crédito: el sobrante queda asociado al huésped (persiste entre estadías).
          - Vuelto:  desglose multimoneda / multicaja para devolver el efectivo.
        """
        change_bs = change_usd * self.exchange_rate

        self._credit_radio = ft.RadioGroup(
            content=ft.Column(
                controls=[
                    ft.Radio(
                        value="credit",
                        label=f"Dejar ${change_usd:.2f} como saldo a favor del huésped"
                              f"  (Bs. {change_bs:,.2f})",
                    ),
                    ft.Radio(
                        value="change",
                        label="Entregar vuelto en este momento",
                    ),
                ],
            ),
            value="credit",   # Por defecto, crédito (más seguro operativamente)
        )

        # ── Campos de distribución del vuelto ───────────────────────────
        v_main_usd  = ft.TextField(label="Caja Ppal. $",  value=f"{change_usd:.2f}",
                                   width=120, text_align=ft.TextAlign.RIGHT)
        v_petty_usd = ft.TextField(label="Caja Chica $",  value="0.00",
                                   width=120, text_align=ft.TextAlign.RIGHT)
        v_main_bs   = ft.TextField(label="Ppal. Bs",       value="0.00",
                                   width=120, text_align=ft.TextAlign.RIGHT)
        v_petty_bs  = ft.TextField(label="Chica Bs",       value="0.00",
                                   width=120, text_align=ft.TextAlign.RIGHT)
        diff_text   = ft.Text("", size=11)

        self._change_fields = (v_main_usd, v_petty_usd, v_main_bs, v_petty_bs)
        self._change_usd    = change_usd

        def validate_distribution(_):
            """Verifica que la suma del desglose cuadre con el sobrante."""
            try:
                total_v = (
                    float(v_main_usd.value  or 0)
                    + float(v_petty_usd.value or 0)
                    + (float(v_main_bs.value or 0) + float(v_petty_bs.value or 0))
                    / self.exchange_rate
                )
                diff = change_usd - total_v
                if abs(diff) < 0.02:
                    diff_text.value = "✅ Distribución correcta"
                    diff_text.color = ft.Colors.GREEN_700
                else:
                    diff_text.value = f"❌ Diferencia: ${diff:.2f}"
                    diff_text.color = ft.Colors.RED_700
                self.page.update()
            except Exception:
                pass

        for field in self._change_fields:
            field.on_change = validate_distribution

        change_breakdown = ft.Column(
            controls=[
                ft.Text("Distribución del vuelto por caja/moneda:",
                        size=11, color=ft.Colors.GREY_700),
                ft.Row(controls=[v_main_usd, v_petty_usd, v_main_bs, v_petty_bs],
                       spacing=8, wrap=True),
                diff_text,
            ],
            spacing=6,
            visible=False,  # Solo visible cuando el modo es "change"
        )

        def on_mode_change(_):
            change_breakdown.visible = self._credit_radio.value == "change"
            self.page.update()

        self._credit_radio.on_change = on_mode_change

        self._change_section.visible = True
        self._change_section.content = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.ORANGE_700, size=16),
                            ft.Text(
                                f"Sobrante: ${change_usd:.2f}  ·  Bs. {change_bs:,.2f}",
                                weight="bold", color=ft.Colors.ORANGE_700, size=13,
                            ),
                        ],
                        spacing=6,
                    ),
                    self._credit_radio,
                    change_breakdown,
                ],
                spacing=10,
            ),
            bgcolor=ft.Colors.ORANGE_50,
            padding=14,
            border_radius=10,
            border=ft.border.all(1, ft.Colors.ORANGE_200),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PERSISTENCIA — TRANSACCIÓN FINAL
    # ═══════════════════════════════════════════════════════════════════════

    def _finalize_payment(self, _):
        """
        Graba todos los pagos de la sesión y gestiona el sobrante
        en una única transacción atómica. Si algo falla se hace
        rollback completo para no dejar la BD en estado inconsistente.
        """
        db = SessionLocal()
        try:
            caja = db.query(CashDrawer).first()
            if not caja:
                raise Exception("No se encontró el registro de caja en la base de datos.")

            # ── 1. Registrar todos los pagos de la sesión ────────────────
            for p in self.session_payments:
                db.add(Payment(
                    stay_id       = self.stay_id,
                    amount_usd    = p["amount_usd"],
                    amount_bs     = p["amount_bs"],
                    exchange_rate = self.exchange_rate,
                    method        = p["method"],
                    reference     = p["reference"] or "—",
                    description   = "Cobro factura",
                    created_at    = datetime.now(),
                    is_refund     = False,
                ))

                # Actualizar saldo de caja según moneda del método
                if p["method"] in [
                    PaymentMethod.CASH_USD,
                    PaymentMethod.ZELLE,
                    PaymentMethod.DEBIT_CARD,
                ]:
                    caja.main_balance_usd += p["amount_usd"]
                else:
                    # Bs (efectivo, transferencia, pago móvil)
                    caja.main_balance_bs += p["amount_bs"]

            # ── 2. Gestionar sobrante si lo hay ─────────────────────────
            remaining = self._calc_remaining()
            if remaining < -0.01:
                change_usd  = abs(remaining)
                last_method = (
                    self.session_payments[-1]["method"]
                    if self.session_payments
                    else PaymentMethod.CASH_USD
                )

                if self._credit_radio and self._credit_radio.value == "credit":
                    # ── Modo crédito ────────────────────────────────────
                    # El saldo queda asociado al HUÉSPED para que persista
                    # en futuras estadías (columna credit_balance_usd en Guest).
                    stay_db = db.get(Stay, self.stay_id)
                    if stay_db and stay_db.guests:
                        guest = db.get(Guest, stay_db.guests[0].id)
                        if guest:
                            current_credit = guest.credit_balance_usd or 0.0
                            guest.credit_balance_usd = current_credit + change_usd

                    # También se refleja en la estadía actual para que el folio cuadre.
                    if stay_db:
                        stay_db.deposit_balance_usd += change_usd

                    db.add(Payment(
                        stay_id       = self.stay_id,
                        amount_usd    = change_usd,
                        amount_bs     = change_usd * self.exchange_rate,
                        is_refund     = True,
                        method        = last_method,
                        exchange_rate = self.exchange_rate,
                        description   = "Sobrante registrado como saldo a favor del huésped",
                        created_at    = datetime.now(),
                    ))

                else:
                    # ── Modo vuelto en efectivo ─────────────────────────
                    vm_usd, vp_usd, vm_bs_f, vp_bs_f = self._change_fields
                    vm_usd_val = float(vm_usd.value  or 0)
                    vp_usd_val = float(vp_usd.value  or 0)
                    vm_bs_val  = float(vm_bs_f.value  or 0)
                    vp_bs_val  = float(vp_bs_f.value  or 0)

                    # Validar fondos disponibles en cada caja antes de descontar
                    if caja.main_balance_usd  < vm_usd_val:
                        raise Exception("Fondos insuficientes — Caja Principal $")
                    if caja.petty_cash_usd    < vp_usd_val:
                        raise Exception("Fondos insuficientes — Caja Chica $")
                    if caja.main_balance_bs   < vm_bs_val:
                        raise Exception("Fondos insuficientes — Caja Principal Bs")
                    if caja.petty_cash_bs     < vp_bs_val:
                        raise Exception("Fondos insuficientes — Caja Chica Bs")

                    caja.main_balance_usd -= vm_usd_val
                    caja.petty_cash_usd   -= vp_usd_val
                    caja.main_balance_bs  -= vm_bs_val
                    caja.petty_cash_bs    -= vp_bs_val

                    db.add(Payment(
                        stay_id       = self.stay_id,
                        amount_usd    = change_usd,
                        amount_bs     = change_usd * self.exchange_rate,
                        is_refund     = True,
                        method        = last_method,
                        exchange_rate = self.exchange_rate,
                        description   = (
                            f"Vuelto multimoneda — "
                            f"P$:{vm_usd_val:.2f} | C$:{vp_usd_val:.2f} | "
                            f"PBs:{vm_bs_val:.2f} | CBs:{vp_bs_val:.2f}"
                        ),
                        created_at    = datetime.now(),
                    ))

            # ── Commit único: todo o nada ────────────────────────────────
            db.commit()

            self.page.close(self.dialog)
            self.page.open(
                ft.SnackBar(
                    ft.Text("✅ Cobro registrado correctamente"),
                    bgcolor=ft.Colors.GREEN_700,
                )
            )
            if self.on_success:
                self.on_success()

        except Exception as e:
            db.rollback()
            self.page.open(
                ft.SnackBar(ft.Text(f"Error al registrar el pago: {str(e)}"),
                            bgcolor=ft.Colors.RED_700)
            )
        finally:
            db.close()

    # ══════════════════════════════════════════

    def show(self):
        self.dialog = self.build()
        self.page.open(self.dialog)