# modules/finance/payment_dialog.py
# Compatible con Flet 0.28.3

import flet as ft
from database.connection import SesionLocal
from database.models import Pago, Caja, MetodoPago, Configuracion, Estadia, Huesped, Habitacion
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN VISUAL POR MÉTODO DE PAGO
# ══════════════════════════════════════════════════════════════════════════════
# Cada clave es un MetodoPago; el valor describe cómo mostrarlo en la UI.
# "es_bs": True  → el recepcionista ingresa el monto en bolívares.
# "es_bs": False → el recepcionista ingresa el monto en dólares.

CONFIGURACION_METODOS = {
    MetodoPago.CASH_USD: {
        "etiqueta": "Efectivo $",
        "icono":    ft.Icons.ATTACH_MONEY,
        "color":    ft.Colors.GREEN_800,
        "es_bs":    False,
    },
    MetodoPago.CASH_BS: {
        "etiqueta": "Efectivo Bs",
        "icono":    ft.Icons.MONEY,
        "color":    ft.Colors.TEAL_700,
        "es_bs":    True,
    },
    MetodoPago.TRANSFER_BS: {
        "etiqueta": "Transferencia",
        "icono":    ft.Icons.SWAP_HORIZ,
        "color":    ft.Colors.BLUE_700,
        "es_bs":    True,
    },
    MetodoPago.PAGO_MOVIL: {
        "etiqueta": "Pago Móvil",
        "icono":    ft.Icons.PHONE_ANDROID,
        "color":    ft.Colors.PURPLE_700,
        "es_bs":    True,
    },
    MetodoPago.ZELLE: {
        "etiqueta": "Zelle",
        "icono":    ft.Icons.SEND,
        "color":    ft.Colors.INDIGO_700,
        "es_bs":    False,
    },
    MetodoPago.DEBIT_CARD: {
        "etiqueta": "T. Débito",
        "icono":    ft.Icons.CREDIT_CARD,
        "color":    ft.Colors.ORANGE_700,
        "es_bs":    False,
    },
}


class DialogoPago:
    """
    Diálogo de cobro con dos paneles en paralelo.

    PANEL IZQUIERDO ── Factura detallada del folio con saldo dinámico.
                       Se actualiza en tiempo real con cada pago añadido.

    PANEL DERECHO ───── Área operativa: métodos de pago, formulario de entrada,
                        lista de pagos de la sesión y sección de sobrante/vuelto.

    Flujo principal:
      1. El recepcionista pulsa un método de pago → aparece el formulario.
      2. Ingresa el monto → pulsa "AGREGAR PAGO".
      3. El pago aparece en la lista y el saldo se actualiza al instante.
      4. Puede agregar más pagos (distintos métodos) hasta cubrir el total.
      5. Si el cliente paga de más, aparece la sección de sobrante con dos opciones:
           a) Dejar como saldo a favor (queda ligado al Huesped, persiste entre estadías).
           b) Entregar vuelto en efectivo con desglose multimoneda / multicaja.
      6. Al finalizar se graba todo en la BD en una única transacción atómica.
    """

    def __init__(self, pagina: ft.Page, estadia, total_a_pagar: float, al_completar):
        self.pagina         = pagina
        self.estadia        = estadia
        self.id_estadia     = estadia.id    # Guardamos el ID; el objeto puede estar detached
        self.total_a_pagar  = total_a_pagar # Saldo neto pendiente al abrir el diálogo
        self.al_completar   = al_completar
        self.dialogo        = None

        # ── Estado de la sesión de cobro ──────────────────────────────────────
        # Lista de pagos añadidos en ESTA sesión (todavía NO grabados en la BD).
        # Cada elemento es un dict con los campos necesarios para crear un Pago.
        self.pagos_sesion: list   = []
        self.tasa_cambio: float   = 1.0
        self.porcentaje_iva: float = 0.0

        # ── Referencias a widgets dinámicos ───────────────────────────────────
        # Mantener referencias directas evita reconstruir todo el árbol con cada actualización.
        self.columna_saldo        = ft.Column(spacing=6)    # Saldo en el panel izquierdo
        self.columna_pagos_sesion = ft.Column(spacing=6)    # Lista de pagos de la sesión
        self.area_formulario      = ft.Column(spacing=8)    # Formulario del método activo
        self.seccion_sobrante     = ft.Container(visible=False)  # Sobrante / vuelto
        self.btn_finalizar        = None                    # Se instancia en construir()

        # Referencias para procesar el sobrante al finalizar
        self.radio_tipo_sobrante = None   # RadioGroup: crédito vs vuelto
        self.campos_desglose_vuelto = None  # Tupla de 4 TextFields del desglose
        self.monto_sobrante_usd  = 0.0    # Monto calculado del sobrante

        self.cargar_configuracion()

    # ══════════════════════════════════════════════════════════════════════════
    # CARGA DE CONFIGURACIÓN
    # ══════════════════════════════════════════════════════════════════════════

    def cargar_configuracion(self):
        """Lee la tasa de cambio y el porcentaje de IVA desde la tabla de configuración."""
        sesion = SesionLocal()
        try:
            config_tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            config_iva = sesion.query(Configuracion).filter(
                Configuracion.clave == "tax_percentage"
            ).first()
            self.tasa_cambio    = float(config_tasa.valor) if config_tasa else 1.0
            self.porcentaje_iva = float(config_iva.valor)  if config_iva  else 0.0
        finally:
            sesion.close()

    # ══════════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS DEL FOLIO
    # ══════════════════════════════════════════════════════════════════════════

    def obtener_datos_factura(self, sesion) -> dict:
        """
        Carga el folio completo desde la BD (siempre fresco para evitar
        objetos detached de SQLAlchemy entre sesiones).
        """
        from sqlalchemy.orm import selectinload

        estadia = (
            sesion.query(Estadia)
            .options(
                selectinload(Estadia.huespedes),
                selectinload(Estadia.cargos_extras),
                selectinload(Estadia.pagos),
            )
            .filter(Estadia.id == self.id_estadia)
            .first()
        )
        habitacion = sesion.query(Habitacion).filter(
            Habitacion.id == estadia.habitacion_id
        ).first()

        # ── Líneas del folio ──────────────────────────────────────────────────
        noches       = max(1, (estadia.salida.date() - estadia.entrada.date()).days)
        precio_noche = habitacion.precio_actual_usd or habitacion.precio_base_usd

        lineas_consumo = [
            {
                "concepto": (
                    f"Hospedaje — Hab. {habitacion.numero} "
                    f"({noches} noche{'s' if noches > 1 else ''})"
                ),
                "cantidad": noches,
                "unitario": precio_noche,
                "total":    noches * precio_noche,
            }
        ]
        for cargo in estadia.cargos_extras:
            cant = max(cargo.cantidad, 1)
            lineas_consumo.append({
                "concepto": cargo.nombre_servicio,
                "cantidad": cant,
                "unitario": cargo.monto_usd / cant,
                "total":    cargo.monto_usd,
            })

        subtotal = sum(linea["total"] for linea in lineas_consumo)
        # IVA se calcula sobre total_a_pagar para respetar abonos previos
        iva      = round(self.total_a_pagar * (self.porcentaje_iva / 100), 2)
        total    = subtotal + iva

        # ── Pagos ya grabados en BD (sesiones anteriores) ─────────────────────
        pagos_previos = [p for p in estadia.pagos if not p.es_devolucion]

        return {
            "estadia":        estadia,
            "habitacion":     habitacion,
            "lineas_consumo": lineas_consumo,
            "subtotal":       subtotal,
            "iva":            iva,
            "total":          total,
            "pagos_previos":  pagos_previos,
            "titular":        estadia.huespedes[0] if estadia.huespedes else None,
            "fecha_entrada":  estadia.entrada.strftime("%d/%m/%Y"),
            "fecha_salida":   estadia.salida.strftime("%d/%m/%Y"),
        }

    # ══════════════════════════════════════════════════════════════════════════
    # CÁLCULO DE SALDO EN TIEMPO REAL
    # ══════════════════════════════════════════════════════════════════════════

    def calcular_saldo_pendiente(self) -> float:
        """
        Retorna el saldo pendiente en USD.
          > 0  → el cliente aún debe dinero
          ≈ 0  → cuenta saldada exactamente
          < 0  → el cliente pagó de más (sobrante)

        total_a_pagar ya incluye los abonos previos grabados en la BD.
        El IVA se suma porque forma parte del cobro pendiente.
        """
        total_abonado_sesion = sum(p["monto_usd"] for p in self.pagos_sesion)
        iva                  = round(self.total_a_pagar * (self.porcentaje_iva / 100), 2)
        return self.total_a_pagar - total_abonado_sesion + iva

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN PRINCIPAL DE LA UI
    # ══════════════════════════════════════════════════════════════════════════

    def construir(self) -> ft.AlertDialog:
        sesion = SesionLocal()
        try:
            datos_factura = self.obtener_datos_factura(sesion)
        finally:
            sesion.close()

        self.btn_finalizar = ft.ElevatedButton(
            text="FINALIZAR COBRO",
            icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
            bgcolor=ft.Colors.GREY_400,
            color=ft.Colors.WHITE,
            disabled=True,
            on_click=self.finalizar_cobro,
            height=46,
        )

        panel_izquierdo = self.construir_panel_factura(datos_factura)
        panel_derecho   = self.construir_panel_cobro()

        cuerpo = ft.Row(
            controls=[
                # Panel izquierdo: factura con fondo gris muy suave
                ft.Container(
                    content=panel_izquierdo,
                    width=310,
                    bgcolor=ft.Colors.GREY_50,
                    border=ft.border.only(right=ft.border.BorderSide(1, ft.Colors.GREY_200)),
                    padding=18,
                ),
                # Panel derecho: área de cobro
                ft.Container(content=panel_derecho, expand=True, padding=18),
            ],
            spacing=0, expand=True,
        )

        self.dialogo = ft.AlertDialog(
            title=self.construir_encabezado(datos_factura),
            content=ft.Container(content=cuerpo, width=860, height=530),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                self.btn_finalizar,
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        return self.dialogo

    # ── Encabezado del diálogo ─────────────────────────────────────────────────

    def construir_encabezado(self, datos_factura) -> ft.Row:
        titular = datos_factura["titular"]
        return ft.Row(
            controls=[
                ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE_800, size=22),
                ft.Column(
                    controls=[
                        ft.Text(
                            f"Factura — Habitación {datos_factura['habitacion'].numero}",
                            weight="bold", size=15,
                        ),
                        ft.Text(
                            titular.nombre_completo if titular else "Huésped",
                            size=11, color=ft.Colors.GREY_600,
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
                            ft.Text(
                                f"Tasa: Bs. {self.tasa_cambio:,.2f}",
                                size=12, color=ft.Colors.GREY_700,
                            ),
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

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL IZQUIERDO — FACTURA
    # ══════════════════════════════════════════════════════════════════════════

    def construir_panel_factura(self, datos_factura) -> ft.Column:
        """
        Construye la columna izquierda con el folio completo.
        La parte inferior (columna_saldo) se actualiza dinámicamente con cada pago.
        """
        # ── Filas de consumos ────────────────────────────────────────────────
        filas_consumos = []
        for linea in datos_factura["lineas_consumo"]:
            filas_consumos.append(
                ft.Row(controls=[
                    ft.Text(linea["concepto"],  size=11, expand=4, color=ft.Colors.BLACK87),
                    ft.Text(
                        f"x{linea['cantidad']}", size=10, expand=1,
                        color=ft.Colors.GREY_600,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        f"${linea['total']:.2f}", size=11, expand=2,
                        text_align=ft.TextAlign.RIGHT, weight="bold",
                    ),
                ])
            )

        # ── Filas de pagos previos (ya grabados en BD) ────────────────────────
        filas_previas = []
        for pago in datos_factura["pagos_previos"]:
            filas_previas.append(
                ft.Row(controls=[
                    ft.Icon(ft.Icons.CHECK, size=11, color=ft.Colors.GREEN_700),
                    ft.Text(pago.metodo.value, size=10, expand=True, color=ft.Colors.GREEN_700),
                    ft.Text(
                        f"-${pago.monto_usd:.2f}", size=10,
                        color=ft.Colors.GREEN_700, text_align=ft.TextAlign.RIGHT,
                    ),
                ])
            )

        # Inicializar el bloque de saldo dinámico
        self.columna_saldo.controls = self.generar_filas_saldo()

        # ── Bloque de fechas ──────────────────────────────────────────────────
        fila_fechas = ft.Row(controls=[
            ft.Column(controls=[
                ft.Text("Entrada",                  size=9,  color=ft.Colors.GREY_500),
                ft.Text(datos_factura["fecha_entrada"], size=11, weight="bold"),
            ], spacing=1),
            ft.Container(expand=True),
            ft.Column(controls=[
                ft.Text("Salida",                   size=9,  color=ft.Colors.GREY_500),
                ft.Text(datos_factura["fecha_salida"],  size=11, weight="bold"),
            ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
        ])

        # ── Construcción del cuerpo de la factura ─────────────────────────────
        cuerpo_factura = ft.Column(
            controls=[
                fila_fechas,
                ft.Divider(height=1, color=ft.Colors.GREY_300),
                # Cabecera de la tabla
                ft.Row(controls=[
                    ft.Text("Concepto", size=9, weight="bold", color=ft.Colors.GREY_500, expand=4),
                    ft.Text("Cant",     size=9, weight="bold", color=ft.Colors.GREY_500, expand=1,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text("Total",    size=9, weight="bold", color=ft.Colors.GREY_500, expand=2,
                            text_align=ft.TextAlign.RIGHT),
                ]),
                ft.Column(controls=filas_consumos, spacing=7),
                ft.Divider(height=1, color=ft.Colors.GREY_300),
                # Subtotal
                ft.Row(controls=[
                    ft.Text("Subtotal:", size=11, expand=True, color=ft.Colors.GREY_700),
                    ft.Text(f"${datos_factura['subtotal']:.2f}", size=11,
                            text_align=ft.TextAlign.RIGHT),
                ]),
                # IVA
                ft.Row(controls=[
                    ft.Text(
                        f"IVA ({self.porcentaje_iva:.0f}%):", size=11,
                        expand=True, color=ft.Colors.GREY_700,
                    ),
                    ft.Text(f"${datos_factura['iva']:.2f}", size=11,
                            text_align=ft.TextAlign.RIGHT),
                ]),
                # TOTAL con equivalente en Bs
                ft.Container(
                    content=ft.Row(controls=[
                        ft.Text("TOTAL:", size=13, weight="bold", expand=True),
                        ft.Column(controls=[
                            ft.Text(
                                f"${datos_factura['total']:.2f}", size=17,
                                weight="bold", color=ft.Colors.BLUE_900,
                            ),
                            ft.Text(
                                f"Bs. {datos_factura['total'] * self.tasa_cambio:,.2f}",
                                size=10, color=ft.Colors.GREY_600,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                        ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                    ]),
                    bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=8,
                ),
                # Pagos previos (si los hay)
                *(
                    [ft.Divider(height=1), ft.Column(controls=filas_previas, spacing=4)]
                    if filas_previas else []
                ),
                ft.Divider(height=1, color=ft.Colors.GREY_300),
                # Saldo dinámico (se refresca en cada pago añadido)
                self.columna_saldo,
            ],
            spacing=8,
        )

        return ft.Column(
            controls=[
                ft.Text("DETALLE DEL FOLIO", size=9, weight="bold",
                        color=ft.Colors.BLUE_GREY_400),
                ft.Container(
                    content=cuerpo_factura,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=10,
                    border=ft.border.all(1, ft.Colors.GREY_200),
                    padding=14,
                ),
            ],
            scroll=ft.ScrollMode.AUTO, spacing=10, expand=True,
        )

    def generar_filas_saldo(self) -> list:
        """
        Genera las filas del bloque de saldo.
        Se llama cada vez que pagos_sesion cambia para reflejar el nuevo balance.
        """
        pendiente           = self.calcular_saldo_pendiente()
        total_abonado_sesion = sum(p["monto_usd"] for p in self.pagos_sesion)
        filas               = []

        # Subtotal abonado en esta sesión
        if self.pagos_sesion:
            filas.append(ft.Row(controls=[
                ft.Text("Abonado ahora:", size=11, expand=True, color=ft.Colors.GREEN_700),
                ft.Column(controls=[
                    ft.Text(
                        f"${total_abonado_sesion:.2f}", size=12, weight="bold",
                        color=ft.Colors.GREEN_700, text_align=ft.TextAlign.RIGHT,
                    ),
                    ft.Text(
                        f"Bs. {total_abonado_sesion * self.tasa_cambio:,.2f}",
                        size=10, color=ft.Colors.GREEN_600,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
            ]))

        # Bloque de estado: pendiente / saldado / sobrante
        if pendiente > 0.01:
            filas.append(ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.PENDING, color=ft.Colors.RED_700, size=15),
                        ft.Text("PENDIENTE:", size=12, weight="bold",
                                color=ft.Colors.RED_700, expand=True),
                        ft.Text(f"${pendiente:.2f}", size=15,
                                weight="bold", color=ft.Colors.RED_700),
                    ]),
                    ft.Text(
                        f"Bs. {pendiente * self.tasa_cambio:,.2f}",
                        size=11, color=ft.Colors.RED_400,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ], spacing=3),
                bgcolor=ft.Colors.RED_50, padding=10, border_radius=8,
            ))

        elif pendiente < -0.01:
            sobrante = abs(pendiente)
            filas.append(ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.ARROW_CIRCLE_UP, color=ft.Colors.ORANGE_700, size=15),
                        ft.Text("SOBRANTE:", size=12, weight="bold",
                                color=ft.Colors.ORANGE_700, expand=True),
                        ft.Text(f"${sobrante:.2f}", size=15,
                                weight="bold", color=ft.Colors.ORANGE_700),
                    ]),
                    ft.Text(
                        f"Bs. {sobrante * self.tasa_cambio:,.2f}",
                        size=11, color=ft.Colors.ORANGE_400,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ], spacing=3),
                bgcolor=ft.Colors.ORANGE_50, padding=10, border_radius=8,
            ))

        else:
            filas.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700, size=16),
                    ft.Text("CUENTA SALDADA", size=12, weight="bold",
                            color=ft.Colors.GREEN_700),
                ], spacing=6),
                bgcolor=ft.Colors.GREEN_50, padding=10, border_radius=8,
            ))

        return filas

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL DERECHO — OPERATIVA DE COBRO
    # ══════════════════════════════════════════════════════════════════════════

    def construir_panel_cobro(self) -> ft.Column:
        """
        Construye la columna derecha con métodos de pago, formulario activo,
        lista de pagos de la sesión y sección de sobrante.
        """
        # Placeholder inicial
        self.area_formulario.controls = [
            ft.Container(
                content=ft.Text(
                    "← Selecciona un método para ingresar el pago",
                    size=12, color=ft.Colors.GREY_500, italic=True,
                ),
                padding=ft.padding.symmetric(vertical=12),
            )
        ]

        # Botones de métodos de pago
        botones_metodos = []
        for metodo, config in CONFIGURACION_METODOS.items():
            botones_metodos.append(
                ft.ElevatedButton(
                    text=config["etiqueta"],
                    icon=config["icono"],
                    style=ft.ButtonStyle(
                        color=config["color"],
                        bgcolor=ft.Colors.with_opacity(0.07, config["color"]),
                        shape=ft.RoundedRectangleBorder(radius=8),
                        side=ft.BorderSide(1.2, ft.Colors.with_opacity(0.3, config["color"])),
                    ),
                    height=42,
                    on_click=lambda _, m=metodo: self.seleccionar_metodo(m),
                )
            )

        return ft.Column(
            controls=[
                ft.Text("MÉTODO DE PAGO", size=9, weight="bold",
                        color=ft.Colors.BLUE_GREY_400),
                ft.Row(controls=botones_metodos, wrap=True, spacing=8, run_spacing=8),
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                self.area_formulario,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Row(controls=[
                    ft.Icon(ft.Icons.RECEIPT, size=13, color=ft.Colors.BLUE_GREY_300),
                    ft.Text("PAGOS DE ESTA SESIÓN", size=9, weight="bold",
                            color=ft.Colors.BLUE_GREY_300),
                ], spacing=5),
                self.columna_pagos_sesion,
                self.seccion_sobrante,
            ],
            spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # LÓGICA DE INTERACCIÓN
    # ══════════════════════════════════════════════════════════════════════════

    def seleccionar_metodo(self, metodo: MetodoPago):
        """
        Muestra el formulario de entrada adaptado al método seleccionado.
        Pre-rellena automáticamente con el saldo pendiente como monto sugerido.
        """
        self.metodo_seleccionado = metodo
        config  = CONFIGURACION_METODOS[metodo]
        es_bs   = config["es_bs"]
        necesita_referencia = metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS]

        # Monto sugerido: el pendiente actual en la moneda del método
        pendiente = self.calcular_saldo_pendiente()
        if pendiente > 0:
            valor_sugerido = (
                f"{pendiente * self.tasa_cambio:.2f}" if es_bs
                else f"{pendiente:.2f}"
            )
        else:
            valor_sugerido = "0.00"

        campo_monto = ft.TextField(
            label=f"Monto recibido ({'Bs.' if es_bs else 'USD'})",
            value=valor_sugerido,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
            autofocus=True,
            expand=True,
        )
        campo_referencia = ft.TextField(
            label="Nro. Referencia / Confirmación",
            visible=necesita_referencia,
            expand=True,
        )

        def agregar_este_pago(evento):
            """Valida e incorpora el pago a la lista de la sesión."""
            try:
                valor_ingresado = float(campo_monto.value.replace(",", ".") or 0)
                if valor_ingresado <= 0:
                    campo_monto.error_text = "Ingrese un monto válido"
                    campo_monto.update()
                    return
                campo_monto.error_text = None

                monto_usd = valor_ingresado / self.tasa_cambio if es_bs else valor_ingresado
                monto_bs  = valor_ingresado if es_bs else valor_ingresado * self.tasa_cambio

                self.pagos_sesion.append({
                    "metodo":     metodo,
                    "monto_usd":  monto_usd,
                    "monto_bs":   monto_bs,
                    "referencia": campo_referencia.value.strip() if necesita_referencia else "",
                    "etiqueta":   config["etiqueta"],
                    "color":      config["color"],
                    "icono":      config["icono"],
                    # Texto legible para mostrar en la lista de pagos de la sesión
                    "visualizacion": f"Bs. {valor_ingresado:,.2f}" if es_bs else f"${valor_ingresado:.2f}",
                })
                self.refrescar_interfaz()

            except (ValueError, AttributeError):
                campo_monto.error_text = "Número inválido"
                campo_monto.update()

        # Fila de campos según si necesita referencia
        fila_campos = [campo_monto, campo_referencia] if necesita_referencia else [campo_monto]

        self.area_formulario.controls = [
            ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(config["icono"], color=config["color"], size=18),
                        ft.Text(config["etiqueta"], weight="bold",
                                color=config["color"], size=13),
                    ], spacing=6),
                    ft.Row(controls=fila_campos, spacing=10),
                    ft.ElevatedButton(
                        "+ AGREGAR PAGO",
                        bgcolor=config["color"], color=ft.Colors.WHITE,
                        on_click=agregar_este_pago,
                        expand=True, height=40,
                    ),
                ], spacing=10),
                padding=14,
                bgcolor=ft.Colors.with_opacity(0.04, config["color"]),
                border_radius=10,
                border=ft.border.all(1.5, ft.Colors.with_opacity(0.25, config["color"])),
            )
        ]
        self.pagina.update()

    def refrescar_interfaz(self):
        """
        Actualiza todos los widgets dinámicos tras cualquier cambio en pagos_sesion.
        Es el único punto desde donde se actualizan la factura y el panel de cobro
        para mantener consistencia visual.
        """
        # 1. Actualizar el bloque de saldo en el panel izquierdo
        self.columna_saldo.controls = self.generar_filas_saldo()

        # 2. Reconstruir la lista de pagos de la sesión
        self.columna_pagos_sesion.controls = []
        for indice, pago in enumerate(self.pagos_sesion):
            self.columna_pagos_sesion.controls.append(
                ft.Container(
                    content=ft.Row(controls=[
                        ft.Icon(pago["icono"], size=14, color=pago["color"]),
                        ft.Text(pago["etiqueta"], size=12, expand=True),
                        ft.Text(pago["visualizacion"], size=12, weight="bold"),
                        ft.Text(
                            f"  (${pago['monto_usd']:.2f})",
                            size=10, color=ft.Colors.GREY_600,
                        ),
                        ft.IconButton(
                            ft.Icons.REMOVE_CIRCLE_OUTLINE,
                            icon_size=15,
                            icon_color=ft.Colors.RED_400,
                            tooltip="Quitar este pago",
                            on_click=lambda _, i=indice: self.quitar_pago(i),
                        ),
                    ], spacing=4),
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    bgcolor=ft.Colors.with_opacity(0.06, pago["color"]),
                    border_radius=7,
                )
            )

        # 3. Evaluar el saldo y configurar el botón de finalizar
        pendiente = self.calcular_saldo_pendiente()

        if pendiente < -0.01:
            # Hay sobrante: mostrar opciones de vuelto o crédito
            self.mostrar_seccion_sobrante(abs(pendiente))
            self.btn_finalizar.disabled = False
            self.btn_finalizar.bgcolor  = ft.Colors.ORANGE_700
            self.btn_finalizar.text     = "CONFIRMAR Y GESTIONAR SOBRANTE"

        elif abs(pendiente) <= 0.01 and self.pagos_sesion:
            # Pago exacto: habilitar finalizar
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled   = False
            self.btn_finalizar.bgcolor    = ft.Colors.GREEN_700
            self.btn_finalizar.text       = "FINALIZAR COBRO"

        else:
            # Aún falta dinero por cobrar
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled   = True
            self.btn_finalizar.bgcolor    = ft.Colors.GREY_400
            self.btn_finalizar.text       = "FINALIZAR COBRO"

        self.pagina.update()

    def quitar_pago(self, indice: int):
        """Elimina un pago de la sesión actual y refresca la interfaz."""
        self.pagos_sesion.pop(indice)
        self.refrescar_interfaz()

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN DE SOBRANTE / VUELTO
    # ══════════════════════════════════════════════════════════════════════════

    def mostrar_seccion_sobrante(self, sobrante_usd: float):
        """
        Construye y muestra la sección de sobrante.
        Ofrece dos modos:
          - Crédito: el sobrante queda asociado al Huesped (persiste entre estadías).
          - Vuelto:  desglose multimoneda / multicaja para devolver el efectivo.
        """
        sobrante_bs = sobrante_usd * self.tasa_cambio

        self.radio_tipo_sobrante = ft.RadioGroup(
            content=ft.Column(controls=[
                ft.Radio(
                    value="credito",
                    label=(
                        f"Dejar ${sobrante_usd:.2f} como saldo a favor del huésped"
                        f"  (Bs. {sobrante_bs:,.2f})"
                    ),
                ),
                ft.Radio(value="vuelto", label="Entregar vuelto en este momento"),
            ]),
            value="credito",  # Por defecto, crédito (más seguro operativamente)
        )

        # ── Campos de desglose del vuelto ─────────────────────────────────────
        campo_principal_usd = ft.TextField(
            label="Caja Ppal. $",  value=f"{sobrante_usd:.2f}",
            width=120, text_align=ft.TextAlign.RIGHT,
        )
        campo_chica_usd = ft.TextField(
            label="Caja Chica $", value="0.00",
            width=120, text_align=ft.TextAlign.RIGHT,
        )
        campo_principal_bs = ft.TextField(
            label="Ppal. Bs",     value="0.00",
            width=120, text_align=ft.TextAlign.RIGHT,
        )
        campo_chica_bs = ft.TextField(
            label="Chica Bs",     value="0.00",
            width=120, text_align=ft.TextAlign.RIGHT,
        )
        texto_diferencia = ft.Text("", size=11)

        self.campos_desglose_vuelto = (
            campo_principal_usd, campo_chica_usd, campo_principal_bs, campo_chica_bs
        )
        self.monto_sobrante_usd = sobrante_usd

        def validar_desglose(evento):
            """Verifica que la suma del desglose cuadre exactamente con el sobrante."""
            try:
                total_desglosado = (
                    float(campo_principal_usd.value or 0)
                    + float(campo_chica_usd.value    or 0)
                    + (
                        float(campo_principal_bs.value or 0)
                        + float(campo_chica_bs.value    or 0)
                    ) / self.tasa_cambio
                )
                diferencia = sobrante_usd - total_desglosado
                if abs(diferencia) < 0.02:
                    texto_diferencia.value = "Distribución correcta"
                    texto_diferencia.color = ft.Colors.GREEN_700
                else:
                    texto_diferencia.value = f"Diferencia: ${diferencia:.2f}"
                    texto_diferencia.color = ft.Colors.RED_700
                self.pagina.update()
            except Exception:
                pass

        for campo in self.campos_desglose_vuelto:
            campo.on_change = validar_desglose

        desglose_vuelto = ft.Column(
            controls=[
                ft.Text("Distribución del vuelto por caja/moneda:",
                        size=11, color=ft.Colors.GREY_700),
                ft.Row(
                    controls=[
                        campo_principal_usd, campo_chica_usd,
                        campo_principal_bs,  campo_chica_bs,
                    ],
                    spacing=8, wrap=True,
                ),
                texto_diferencia,
            ],
            spacing=6,
            visible=False,  # Solo visible cuando el modo es "vuelto"
        )

        def al_cambiar_modo(evento):
            desglose_vuelto.visible = (self.radio_tipo_sobrante.value == "vuelto")
            self.pagina.update()

        self.radio_tipo_sobrante.on_change = al_cambiar_modo

        self.seccion_sobrante.visible = True
        self.seccion_sobrante.content = ft.Container(
            content=ft.Column(controls=[
                ft.Row(controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.ORANGE_700, size=16),
                    ft.Text(
                        f"Sobrante: ${sobrante_usd:.2f}  ·  Bs. {sobrante_bs:,.2f}",
                        weight="bold", color=ft.Colors.ORANGE_700, size=13,
                    ),
                ], spacing=6),
                self.radio_tipo_sobrante,
                desglose_vuelto,
            ], spacing=10),
            bgcolor=ft.Colors.ORANGE_50,
            padding=14,
            border_radius=10,
            border=ft.border.all(1, ft.Colors.ORANGE_200),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PERSISTENCIA — TRANSACCIÓN FINAL
    # ══════════════════════════════════════════════════════════════════════════

    def finalizar_cobro(self, evento):
        """
        Graba todos los pagos de la sesión y gestiona el sobrante
        en una única transacción atómica.
        Si algo falla, hace rollback completo para no dejar la BD inconsistente.
        """
        sesion = SesionLocal()
        try:
            caja = sesion.query(Caja).first()
            if not caja:
                raise Exception("No se encontró el registro de caja en la base de datos.")

            # ── 1. Registrar todos los pagos de la sesión ─────────────────────
            for pago in self.pagos_sesion:
                sesion.add(Pago(
                    estadia_id    = self.id_estadia,
                    monto_usd     = pago["monto_usd"],
                    monto_bs      = pago["monto_bs"],
                    tasa_cambio   = self.tasa_cambio,
                    metodo        = pago["metodo"],
                    referencia    = pago["referencia"] or "—",
                    descripcion   = "Cobro de factura",
                    creado_en     = datetime.now(),
                    es_devolucion = False,
                ))

                # Actualizar saldo de caja según la moneda del método
                if pago["metodo"] in [MetodoPago.CASH_USD, MetodoPago.ZELLE, MetodoPago.DEBIT_CARD]:
                    caja.saldo_principal_usd += pago["monto_usd"]
                else:
                    # Bs (efectivo, transferencia, pago móvil)
                    caja.saldo_principal_bs += pago["monto_bs"]

            # ── 2. Gestionar el sobrante si lo hay ────────────────────────────
            pendiente = self.calcular_saldo_pendiente()
            if pendiente < -0.01:
                monto_sobrante = abs(pendiente)
                ultimo_metodo  = (
                    self.pagos_sesion[-1]["metodo"] if self.pagos_sesion
                    else MetodoPago.CASH_USD
                )

                if self.radio_tipo_sobrante and self.radio_tipo_sobrante.value == "credito":
                    # ── Modo crédito: el saldo queda en el Huesped ────────────
                    # Persiste entre estadías mediante el campo credito_usd en Huesped.
                    estadia_bd = sesion.get(Estadia, self.id_estadia)
                    if estadia_bd and estadia_bd.huespedes:
                        huesped = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                        if huesped:
                            credito_actual = huesped.credito_usd or 0.0
                            huesped.credito_usd = credito_actual + monto_sobrante

                    # También se refleja en la estadía actual para que el folio cuadre
                    if estadia_bd:
                        estadia_bd.deposito_usd += monto_sobrante

                    sesion.add(Pago(
                        estadia_id    = self.id_estadia,
                        monto_usd     = monto_sobrante,
                        monto_bs      = monto_sobrante * self.tasa_cambio,
                        es_devolucion = True,
                        metodo        = ultimo_metodo,
                        tasa_cambio   = self.tasa_cambio,
                        descripcion   = "Sobrante registrado como saldo a favor del huésped",
                        creado_en     = datetime.now(),
                    ))

                else:
                    # ── Modo vuelto en efectivo ────────────────────────────────
                    c_ppal, c_chica, c_ppal_bs, c_chica_bs = self.campos_desglose_vuelto
                    val_ppal    = float(c_ppal.value    or 0)
                    val_chica   = float(c_chica.value   or 0)
                    val_ppal_bs = float(c_ppal_bs.value or 0)
                    val_chica_bs = float(c_chica_bs.value or 0)

                    # Validar fondos disponibles antes de descontar
                    if caja.saldo_principal_usd < val_ppal:
                        raise Exception("Fondos insuficientes — Caja Principal $")
                    if caja.caja_chica_usd < val_chica:
                        raise Exception("Fondos insuficientes — Caja Chica $")
                    if caja.saldo_principal_bs < val_ppal_bs:
                        raise Exception("Fondos insuficientes — Caja Principal Bs")
                    if caja.caja_chica_bs < val_chica_bs:
                        raise Exception("Fondos insuficientes — Caja Chica Bs")

                    caja.saldo_principal_usd -= val_ppal
                    caja.caja_chica_usd       -= val_chica
                    caja.saldo_principal_bs   -= val_ppal_bs
                    caja.caja_chica_bs        -= val_chica_bs

                    sesion.add(Pago(
                        estadia_id    = self.id_estadia,
                        monto_usd     = monto_sobrante,
                        monto_bs      = monto_sobrante * self.tasa_cambio,
                        es_devolucion = True,
                        metodo        = ultimo_metodo,
                        tasa_cambio   = self.tasa_cambio,
                        descripcion   = (
                            f"Vuelto multimoneda — "
                            f"P$:{val_ppal:.2f} | C$:{val_chica:.2f} | "
                            f"PBs:{val_ppal_bs:.2f} | CBs:{val_chica_bs:.2f}"
                        ),
                        creado_en     = datetime.now(),
                    ))

            # ── Commit único: todo o nada ──────────────────────────────────────
            sesion.commit()

            self.pagina.close(self.dialogo)
            self.pagina.open(ft.SnackBar(
                ft.Text("Cobro registrado correctamente"),
                bgcolor=ft.Colors.GREEN_700,
            ))
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error al registrar el pago: {str(error)}"),
                bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()

    # ══════════════════════════════════════════════════════════════════════════

    def mostrar(self):
        """Construye y abre el diálogo de cobro."""
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)