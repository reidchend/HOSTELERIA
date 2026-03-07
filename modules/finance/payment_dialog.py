# modules/finance/payment_dialog.py
# Compatible con Flet 0.28.3

import flet as ft
from database.connection import SesionLocal
from database.models import (
    Pago, Caja, MetodoPago, Estadia, Huesped,
    LineaCuenta, TipoLinea, TransaccionCobro,
)
from sqlalchemy.orm import selectinload
from datetime import datetime
from utils.calculos_financieros import leer_config_financiera, a_bs, a_usd

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN VISUAL POR MÉTODO DE PAGO
# ══════════════════════════════════════════════════════════════════════════════

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
    Diálogo de cobro con soporte para IVA mixto y pagos parciales.

    PANEL IZQUIERDO ── Detalle de las líneas seleccionadas a cobrar,
                       con desglose de IVA por tipo de línea y saldo dinámico.

    PANEL DERECHO ───── Métodos de pago, formulario de entrada,
                        lista de pagos de la sesión y gestión de sobrante/vuelto.

    LÓGICA DE IVA:
      · Hospedaje  → el monto en LineaCuenta NO incluye IVA (la hab. está exenta
                     o el IVA ya fue considerado por separado en el precio base).
                     Se muestra sin recargo adicional.
      · Cargo extra → el monto en LineaCuenta ya incluye IVA (el recepcionista
                      ingresa el precio final). Se muestra como viene.

    PAGO PARCIAL:
      Si el cliente paga menos del total seleccionado, al finalizar se crea
      una TransaccionCobro que registra:
        - Las líneas originales → marcadas canceladas (agrupadas bajo la transacción)
        - Una nueva LineaCuenta SALDO_PENDIENTE con la diferencia → cobrable después

    HISTORIAL:
      details.py agrupa las líneas por TransaccionCobro para mostrar
      "Factura #N — pagado $X — pendiente $Y" con sus conceptos anidados.
    """

    def __init__(
        self,
        pagina:          ft.Page,
        estadia,
        total_a_pagar:   float,
        al_completar,
        lineas_ids:      list[int] | None = None,   # IDs de LineaCuenta seleccionadas
    ):
        self.pagina        = pagina
        self.estadia       = estadia
        self.id_estadia    = estadia.id
        self.total_a_pagar = total_a_pagar   # Suma de monto_usd de las líneas seleccionadas
        self.al_completar  = al_completar
        self.lineas_ids    = lineas_ids or []
        self.dialogo       = None

        sesion = SesionLocal()
        try:
            self.config = leer_config_financiera(sesion)
            estadia_bd  = sesion.get(Estadia, estadia.id)
            self.saldo_favor_disponible = estadia_bd.deposito_usd or 0.0
        finally:
            sesion.close()

        self.pagos_sesion: list = []

        # Widgets dinámicos
        self.columna_saldo        = ft.Column(spacing=6)
        self.columna_pagos_sesion = ft.Column(spacing=6)
        self.area_formulario      = ft.Column(spacing=8)
        self.seccion_sobrante     = ft.Container(visible=False)
        self.btn_finalizar        = None

        self.radio_tipo_sobrante    = None
        self.campos_desglose_vuelto = None
        self.monto_sobrante_usd     = 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS — LÍNEAS SELECCIONADAS
    # ══════════════════════════════════════════════════════════════════════════

    def _cargar_lineas(self, sesion) -> list:
        """Carga las LineaCuenta seleccionadas (frescas desde la BD)."""
        if not self.lineas_ids:
            return []
        return (
            sesion.query(LineaCuenta)
            .filter(LineaCuenta.id.in_(self.lineas_ids))
            .all()
        )

    def _datos_para_panel(self, sesion) -> dict:
        """Datos del encabezado del diálogo."""
        from sqlalchemy.orm import selectinload
        estadia = (
            sesion.query(Estadia)
            .options(
                selectinload(Estadia.huespedes),
                selectinload(Estadia.habitacion),
                selectinload(Estadia.pagos),
            )
            .filter(Estadia.id == self.id_estadia)
            .first()
        )
        return {
            "estadia":      estadia,
            "habitacion":   estadia.habitacion,
            "titular":      estadia.huespedes[0] if estadia.huespedes else None,
            "pagos_previos":[p for p in estadia.pagos if not p.es_devolucion],
        }

    # ══════════════════════════════════════════════════════════════════════════
    # SALDO EN TIEMPO REAL
    # ══════════════════════════════════════════════════════════════════════════

    def _pendiente(self) -> float:
        abonado = sum(p["monto_usd"] for p in self.pagos_sesion)
        return round(self.total_a_pagar - abonado, 2)

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN DE LA UI
    # ══════════════════════════════════════════════════════════════════════════

    def construir(self) -> ft.AlertDialog:
        sesion = SesionLocal()
        try:
            datos  = self._datos_para_panel(sesion)
            lineas = self._cargar_lineas(sesion)
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

        cuerpo = ft.Row(
            controls=[
                ft.Container(
                    content=self._panel_factura(datos, lineas),
                    width=320,
                    bgcolor=ft.Colors.GREY_50,
                    border=ft.border.only(
                        right=ft.border.BorderSide(1, ft.Colors.GREY_200)
                    ),
                    padding=18,
                ),
                ft.Container(
                    content=self._panel_cobro(),
                    expand=True, padding=18,
                ),
            ],
            spacing=0, expand=True,
        )

        self.dialogo = ft.AlertDialog(
            title=self._encabezado(datos),
            content=ft.Container(content=cuerpo, width=880, height=540),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.pagina.close(self.dialogo),
                ),
                self.btn_finalizar,
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        return self.dialogo

    def _encabezado(self, datos) -> ft.Row:
        titular = datos["titular"]
        return ft.Row(controls=[
            ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE_800, size=22),
            ft.Column(controls=[
                ft.Text(
                    f"Cobro — Habitación {datos['habitacion'].numero}",
                    weight="bold", size=15,
                ),
                ft.Text(
                    titular.nombre_completo if titular else "Huésped",
                    size=11, color=ft.Colors.GREY_600,
                ),
            ], spacing=1),
            ft.Container(expand=True),
            ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(ft.Icons.CURRENCY_EXCHANGE, size=13,
                            color=ft.Colors.GREY_600),
                    ft.Text(
                        f"Tasa: Bs. {self.config.tasa_cambio:,.2f}",
                        size=12, color=ft.Colors.GREY_700,
                    ),
                ], spacing=5),
                bgcolor=ft.Colors.GREY_100,
                padding=ft.padding.symmetric(horizontal=12, vertical=5),
                border_radius=20,
            ),
        ], spacing=10)

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL IZQUIERDO — DETALLE DE LÍNEAS A COBRAR
    # ══════════════════════════════════════════════════════════════════════════

    def _panel_factura(self, datos, lineas: list) -> ft.Column:
        """
        Muestra las líneas seleccionadas con tratamiento de IVA correcto:
          · HOSPEDAJE    → precio sin IVA (se muestra tal cual)
          · CARGO_EXTRA  → precio con IVA ya incluido (se muestra tal cual)
          · SALDO_PENDIENTE → deuda de cobro anterior
        """
        tasa = self.config.tasa_cambio
        filas_lineas = []

        for linea in lineas:
            if linea.tipo == TipoLinea.HOSPEDAJE:
                icono      = ft.Icons.BED_OUTLINED
                color_ico  = ft.Colors.BLUE_700
                etiq_tipo  = "Hospedaje"
                color_tipo = ft.Colors.BLUE_700
            elif linea.tipo == TipoLinea.CARGO_EXTRA:
                icono      = ft.Icons.ROOM_SERVICE
                color_ico  = ft.Colors.ORANGE_700
                etiq_tipo  = "Servicio (c/IVA)"
                color_tipo = ft.Colors.ORANGE_700
            else:
                icono      = ft.Icons.PENDING_ACTIONS
                color_ico  = ft.Colors.RED_700
                etiq_tipo  = "Saldo pendiente"
                color_tipo = ft.Colors.RED_700

            filas_lineas.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(icono, size=14, color=color_ico),
                    ft.Column(controls=[
                        ft.Text(linea.concepto, size=11, color=ft.Colors.BLACK87),
                        ft.Container(
                            content=ft.Text(etiq_tipo, size=9, color=color_tipo),
                            bgcolor=ft.Colors.with_opacity(0.1, color_tipo),
                            padding=ft.padding.symmetric(horizontal=5, vertical=1),
                            border_radius=4,
                        ),
                    ], spacing=2, expand=True),
                    ft.Column(controls=[
                        ft.Text(
                            f"${linea.monto_usd:.2f}",
                            size=12, weight="bold",
                            text_align=ft.TextAlign.RIGHT,
                        ),
                        ft.Text(
                            f"Bs.{a_bs(linea.monto_usd, tasa):,.0f}",
                            size=9, color=ft.Colors.GREY_500,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                ], spacing=8),
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                bgcolor=ft.Colors.WHITE,
                border_radius=7,
                border=ft.border.all(1, ft.Colors.GREY_100),
            ))

        # Nota de IVA mixto
        tiene_hospedaje = any(l.tipo == TipoLinea.HOSPEDAJE for l in lineas)
        tiene_extras    = any(l.tipo == TipoLinea.CARGO_EXTRA for l in lineas)
        nota_iva = []
        if tiene_hospedaje:
            nota_iva.append("🏨 Hospedaje: precio sin IVA")
        if tiene_extras:
            nota_iva.append("🍽 Servicios: precio con IVA incluido")

        self.columna_saldo.controls = self._filas_saldo()

        cuerpo = ft.Column(controls=[
            ft.Text("CONCEPTOS A COBRAR", size=9, weight="bold",
                    color=ft.Colors.BLUE_GREY_400),
            ft.Column(controls=filas_lineas, spacing=5),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            # Nota de IVA
            ft.Column(controls=[
                ft.Text(n, size=9, color=ft.Colors.GREY_500, italic=True)
                for n in nota_iva
            ], spacing=2) if nota_iva else ft.Container(),
            # Total seleccionado
            ft.Container(
                content=ft.Row(controls=[
                    ft.Text("TOTAL A COBRAR:", size=13, weight="bold", expand=True),
                    ft.Column(controls=[
                        ft.Text(
                            f"${self.total_a_pagar:.2f}",
                            size=18, weight="bold", color=ft.Colors.BLUE_900,
                        ),
                        ft.Text(
                            f"Bs. {a_bs(self.total_a_pagar, tasa):,.2f}",
                            size=10, color=ft.Colors.GREY_600,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                ]),
                bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=8,
            ),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            self.columna_saldo,
        ], spacing=8)

        return ft.Column(
            controls=[cuerpo],
            scroll=ft.ScrollMode.AUTO, spacing=10, expand=True,
        )

    def _filas_saldo(self) -> list:
        pendiente            = self._pendiente()
        total_abonado_sesion = sum(p["monto_usd"] for p in self.pagos_sesion)
        tasa                 = self.config.tasa_cambio
        filas                = []

        if self.pagos_sesion:
            filas.append(ft.Row(controls=[
                ft.Text("Abonado ahora:", size=11, expand=True,
                        color=ft.Colors.GREEN_700),
                ft.Column(controls=[
                    ft.Text(f"${total_abonado_sesion:.2f}", size=12, weight="bold",
                            color=ft.Colors.GREEN_700,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Text(f"Bs. {a_bs(total_abonado_sesion, tasa):,.2f}",
                            size=10, color=ft.Colors.GREEN_600,
                            text_align=ft.TextAlign.RIGHT),
                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
            ]))

        if pendiente > 0.01:
            # Pago parcial — aviso de que quedará deuda
            filas.append(ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.PENDING, color=ft.Colors.RED_700, size=15),
                        ft.Text("PENDIENTE:", size=12, weight="bold",
                                color=ft.Colors.RED_700, expand=True),
                        ft.Text(f"${pendiente:.2f}", size=15,
                                weight="bold", color=ft.Colors.RED_700),
                    ]),
                    ft.Text(f"Bs. {a_bs(pendiente, tasa):,.2f}", size=11,
                            color=ft.Colors.RED_400,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Text(
                        "⚠ La diferencia quedará registrada como\n"
                        "   saldo pendiente de esta transacción.",
                        size=9, color=ft.Colors.RED_400, italic=True,
                    ) if self.pagos_sesion else ft.Container(),
                ], spacing=3),
                bgcolor=ft.Colors.RED_50, padding=10, border_radius=8,
            ))
        elif pendiente < -0.01:
            sobrante = abs(pendiente)
            filas.append(ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.ARROW_CIRCLE_UP,
                                color=ft.Colors.ORANGE_700, size=15),
                        ft.Text("SOBRANTE:", size=12, weight="bold",
                                color=ft.Colors.ORANGE_700, expand=True),
                        ft.Text(f"${sobrante:.2f}", size=15,
                                weight="bold", color=ft.Colors.ORANGE_700),
                    ]),
                    ft.Text(f"Bs. {a_bs(sobrante, tasa):,.2f}", size=11,
                            color=ft.Colors.ORANGE_400,
                            text_align=ft.TextAlign.RIGHT),
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

    def _panel_cobro(self) -> ft.Column:
        self.area_formulario.controls = [
            ft.Container(
                content=ft.Text(
                    "← Selecciona un método para ingresar el pago",
                    size=12, color=ft.Colors.GREY_500, italic=True,
                ),
                padding=ft.padding.symmetric(vertical=12),
            )
        ]

        botones = [
            ft.ElevatedButton(
                text=cfg["etiqueta"],
                icon=cfg["icono"],
                style=ft.ButtonStyle(
                    color=cfg["color"],
                    bgcolor=ft.Colors.with_opacity(0.07, cfg["color"]),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    side=ft.BorderSide(1.2, ft.Colors.with_opacity(0.3, cfg["color"])),
                ),
                height=42,
                on_click=lambda _, m=metodo: self.seleccionar_metodo(m),
            )
            for metodo, cfg in CONFIGURACION_METODOS.items()
        ]

        # Botón de saldo a favor — solo visible si hay crédito disponible
        saldo_disp = self.saldo_favor_disponible
        btn_saldo_favor = ft.ElevatedButton(
            text=f"Saldo a Favor  (${saldo_disp:.2f} disp.)",
            icon=ft.Icons.ACCOUNT_BALANCE_WALLET,
            style=ft.ButtonStyle(
                color=ft.Colors.GREEN_900,
                bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.GREEN_800),
                shape=ft.RoundedRectangleBorder(radius=8),
                side=ft.BorderSide(1.5, ft.Colors.GREEN_700),
            ),
            height=42,
            visible=saldo_disp > 0.01,
            on_click=lambda _: self._aplicar_saldo_favor(),
        )

        btn_saldo_externo = ft.OutlinedButton(
            text="Saldo de otro huésped",
            icon=ft.Icons.PERSON_SEARCH,
            style=ft.ButtonStyle(
                color=ft.Colors.TEAL_700,
                side=ft.BorderSide(1.2, ft.Colors.TEAL_300),
            ),
            height=38,
            on_click=lambda _: self._abrir_buscador_huesped_externo(),
        )

        return ft.Column(
            controls=[
                ft.Text("MÉTODO DE PAGO", size=9, weight="bold",
                        color=ft.Colors.BLUE_GREY_400),
                ft.Row(controls=botones, wrap=True, spacing=8, run_spacing=8),
                ft.Row(controls=[btn_saldo_favor, btn_saldo_externo],
                       spacing=8, wrap=True),
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                self.area_formulario,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Row(controls=[
                    ft.Icon(ft.Icons.RECEIPT, size=13,
                            color=ft.Colors.BLUE_GREY_300),
                    ft.Text("PAGOS DE ESTA SESIÓN", size=9, weight="bold",
                            color=ft.Colors.BLUE_GREY_300),
                ], spacing=5),
                self.columna_pagos_sesion,
                self.seccion_sobrante,
            ],
            spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # INTERACCIÓN — SELECCIÓN DE MÉTODO Y ENTRADA DE MONTO
    # ══════════════════════════════════════════════════════════════════════════

    def seleccionar_metodo(self, metodo: MetodoPago):
        cfg                 = CONFIGURACION_METODOS[metodo]
        es_bs               = cfg["es_bs"]
        necesita_referencia = metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS]
        tasa                = self.config.tasa_cambio

        pendiente = self._pendiente()
        if pendiente > 0:
            valor_sugerido = (
                f"{a_bs(pendiente, tasa):.2f}" if es_bs else f"{pendiente:.2f}"
            )
        else:
            valor_sugerido = "0.00"

        campo_monto = ft.TextField(
            label=f"Monto recibido ({'Bs.' if es_bs else 'USD'})",
            value=valor_sugerido,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
            autofocus=True, expand=True,
        )
        campo_referencia = ft.TextField(
            label="Nro. Referencia / Confirmación",
            visible=necesita_referencia, expand=True,
        )

        def agregar_este_pago(evento):
            try:
                valor = float(campo_monto.value.replace(",", ".") or 0)
                if valor <= 0:
                    campo_monto.error_text = "Ingrese un monto válido"
                    campo_monto.update()
                    return
                campo_monto.error_text = None

                monto_usd = a_usd(valor, tasa) if es_bs else valor
                monto_bs  = valor              if es_bs else a_bs(valor, tasa)

                self.pagos_sesion.append({
                    "metodo":        metodo,
                    "monto_usd":     monto_usd,
                    "monto_bs":      monto_bs,
                    "referencia":    campo_referencia.value.strip()
                                     if necesita_referencia else "",
                    "etiqueta":      cfg["etiqueta"],
                    "color":         cfg["color"],
                    "icono":         cfg["icono"],
                    "visualizacion": f"Bs. {valor:,.2f}" if es_bs else f"${valor:.2f}",
                })
                self.refrescar_interfaz()

            except (ValueError, AttributeError):
                campo_monto.error_text = "Número inválido"
                campo_monto.update()

        fila_campos = (
            [campo_monto, campo_referencia] if necesita_referencia else [campo_monto]
        )

        self.area_formulario.controls = [
            ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(cfg["icono"], color=cfg["color"], size=18),
                        ft.Text(cfg["etiqueta"], weight="bold",
                                color=cfg["color"], size=13),
                    ], spacing=6),
                    ft.Row(controls=fila_campos, spacing=10),
                    ft.ElevatedButton(
                        "+ AGREGAR PAGO",
                        bgcolor=cfg["color"], color=ft.Colors.WHITE,
                        on_click=agregar_este_pago,
                        expand=True, height=40,
                    ),
                ], spacing=10),
                padding=14,
                bgcolor=ft.Colors.with_opacity(0.04, cfg["color"]),
                border_radius=10,
                border=ft.border.all(1.5, ft.Colors.with_opacity(0.25, cfg["color"])),
            )
        ]
        self.pagina.update()

    def refrescar_interfaz(self):
        """Actualiza saldo, lista de pagos y estado del botón finalizar."""
        self.columna_saldo.controls = self._filas_saldo()

        self.columna_pagos_sesion.controls = [
            ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(p["icono"], size=14, color=p["color"]),
                    ft.Text(p["etiqueta"], size=12, expand=True),
                    ft.Text(p["visualizacion"], size=12, weight="bold"),
                    ft.Text(f"  (${p['monto_usd']:.2f})", size=10,
                            color=ft.Colors.GREY_600),
                    ft.IconButton(
                        ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        icon_size=15, icon_color=ft.Colors.RED_400,
                        tooltip="Quitar este pago",
                        on_click=lambda _, i=idx: self.quitar_pago(i),
                    ),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                bgcolor=ft.Colors.with_opacity(0.06, p["color"]),
                border_radius=7,
            )
            for idx, p in enumerate(self.pagos_sesion)
        ]

        pendiente = self._pendiente()

        if pendiente < -0.01:
            # Sobrante: el cliente pagó más de lo seleccionado
            self.mostrar_seccion_sobrante(abs(pendiente))
            self.btn_finalizar.disabled = False
            self.btn_finalizar.bgcolor  = ft.Colors.ORANGE_700
            self.btn_finalizar.text     = "CONFIRMAR Y GESTIONAR SOBRANTE"
        elif self.pagos_sesion:
            # Saldado exactamente o pago parcial (pendiente >= 0)
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled   = False
            self.btn_finalizar.bgcolor    = (
                ft.Colors.GREEN_700 if abs(pendiente) <= 0.01
                else ft.Colors.BLUE_700        # azul = pago parcial permitido
            )
            self.btn_finalizar.text = (
                "FINALIZAR COBRO" if abs(pendiente) <= 0.01
                else f"COBRAR PARCIAL (quedan ${pendiente:.2f})"
            )
        else:
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled   = True
            self.btn_finalizar.bgcolor    = ft.Colors.GREY_400
            self.btn_finalizar.text       = "FINALIZAR COBRO"

        self.pagina.update()

    def quitar_pago(self, indice: int):
        self.pagos_sesion.pop(indice)
        self.refrescar_interfaz()

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN DE SOBRANTE / VUELTO
    # ══════════════════════════════════════════════════════════════════════════

    def mostrar_seccion_sobrante(self, sobrante_usd: float):
        tasa        = self.config.tasa_cambio
        sobrante_bs = a_bs(sobrante_usd, tasa)

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
            value="credito",
        )

        campo_ppal_usd   = ft.TextField(label="Caja Ppal. $",
                                        value=f"{sobrante_usd:.2f}", width=120,
                                        text_align=ft.TextAlign.RIGHT)
        campo_chica_usd  = ft.TextField(label="Caja Chica $", value="0.00", width=120,
                                        text_align=ft.TextAlign.RIGHT)
        campo_ppal_bs    = ft.TextField(label="Ppal. Bs",     value="0.00", width=120,
                                        text_align=ft.TextAlign.RIGHT)
        campo_chica_bs   = ft.TextField(label="Chica Bs",     value="0.00", width=120,
                                        text_align=ft.TextAlign.RIGHT)
        texto_diferencia = ft.Text("", size=11)

        self.campos_desglose_vuelto = (
            campo_ppal_usd, campo_chica_usd, campo_ppal_bs, campo_chica_bs
        )
        self.monto_sobrante_usd = sobrante_usd

        def validar_desglose(evento):
            try:
                total = (
                    float(campo_ppal_usd.value  or 0)
                    + float(campo_chica_usd.value or 0)
                    + a_usd(
                        float(campo_ppal_bs.value  or 0)
                        + float(campo_chica_bs.value or 0),
                        tasa,
                    )
                )
                diff = round(sobrante_usd - total, 2)
                if abs(diff) < 0.02:
                    texto_diferencia.value = "Distribución correcta"
                    texto_diferencia.color = ft.Colors.GREEN_700
                else:
                    texto_diferencia.value = f"Diferencia: ${diff:.2f}"
                    texto_diferencia.color = ft.Colors.RED_700
                self.pagina.update()
            except Exception:
                pass

        for campo in self.campos_desglose_vuelto:
            campo.on_change = validar_desglose

        desglose_vuelto = ft.Column(controls=[
            ft.Text("Distribución del vuelto por caja/moneda:",
                    size=11, color=ft.Colors.GREY_700),
            ft.Row(controls=[campo_ppal_usd, campo_chica_usd,
                              campo_ppal_bs,  campo_chica_bs],
                   spacing=8, wrap=True),
            texto_diferencia,
        ], spacing=6, visible=False)

        def al_cambiar_modo(evento):
            desglose_vuelto.visible = (self.radio_tipo_sobrante.value == "vuelto")
            self.pagina.update()

        self.radio_tipo_sobrante.on_change = al_cambiar_modo

        self.seccion_sobrante.visible = True
        self.seccion_sobrante.content = ft.Container(
            content=ft.Column(controls=[
                ft.Row(controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE,
                            color=ft.Colors.ORANGE_700, size=16),
                    ft.Text(
                        f"Sobrante: ${sobrante_usd:.2f}  ·  Bs. {sobrante_bs:,.2f}",
                        weight="bold", color=ft.Colors.ORANGE_700, size=13,
                    ),
                ], spacing=6),
                self.radio_tipo_sobrante,
                desglose_vuelto,
            ], spacing=10),
            bgcolor=ft.Colors.ORANGE_50, padding=14, border_radius=10,
            border=ft.border.all(1, ft.Colors.ORANGE_200),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PERSISTENCIA — TRANSACCIÓN FINAL
    # ══════════════════════════════════════════════════════════════════════════


    def _aplicar_saldo_favor(self):
        """
        Aplica el saldo a favor disponible en la estadía como un pago.
        Solo aplica hasta cubrir el pendiente — no genera sobrante por saldo.
        """
        pendiente   = self._pendiente()
        disponible  = self.saldo_favor_disponible
        if disponible <= 0.01 or pendiente <= 0.01:
            return

        monto_aplicar = round(min(disponible, pendiente), 2)
        tasa          = self.config.tasa_cambio

        self.pagos_sesion.append({
            "metodo":        MetodoPago.SALDO_FAVOR,
            "monto_usd":     monto_aplicar,
            "monto_bs":      a_bs(monto_aplicar, tasa),
            "referencia":    "",
            "etiqueta":      "Saldo a Favor",
            "color":         ft.Colors.GREEN_800,
            "icono":         ft.Icons.ACCOUNT_BALANCE_WALLET,
            "visualizacion": f"${monto_aplicar:.2f}",
            "es_saldo_favor": True,   # flag para tratamiento especial en finalizar_cobro
        })
        self.refrescar_interfaz()


    def _saldo_real_huesped(self, sesion, huesped_id: int) -> float:
        """
        Calcula el saldo total disponible de un huésped en tiempo real:
          · Huesped.credito_usd          → crédito persistente (sin estadía activa)
          · SUM(Estadia.deposito_usd)    → depósitos en estadías activas
        Excluye la estadía actual para no contar dos veces.
        """
        from database.models import Huesped as HuespedModel
        huesped = sesion.get(HuespedModel, huesped_id)
        if not huesped:
            return 0.0

        credito_base = huesped.credito_usd or 0.0

        # Estadías activas del huésped (excepto la estadía actual)
        from sqlalchemy.orm import selectinload as _sl
        estadias_activas = (
            sesion.query(Estadia)
            .options(_sl(Estadia.huespedes))
            .filter(
                Estadia.activa       == True,
                Estadia.id           != self.id_estadia,
                Estadia.deposito_usd >  0,
            )
            .all()
        )
        deposito_estadias = sum(
            e.deposito_usd
            for e in estadias_activas
            if any(h.id == huesped_id for h in e.huespedes)
        )

        return round(credito_base + deposito_estadias, 2)

    def _abrir_buscador_huesped_externo(self):
        """
        Abre un diálogo para buscar un huésped por documento o nombre,
        ver su saldo disponible y aplicarlo como pago a esta cuenta.
        El origen del saldo queda registrado en la descripción del Pago.
        """
        from database.models import Huesped as HuespedModel

        campo_busqueda = ft.TextField(
            label="Buscar por documento o nombre",
            prefix_icon=ft.Icons.SEARCH,
            autofocus=True,
            expand=True,
        )
        lista_resultados  = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
        texto_sin_resultados = ft.Text(
            "Ingresa el documento o nombre para buscar",
            size=12, color=ft.Colors.GREY_400, italic=True,
        )
        lista_resultados.controls = [texto_sin_resultados]

        # Huésped seleccionado y su saldo
        seleccion = {"huesped_id": None, "nombre": "", "saldo": 0.0,
                     "estadia_origen_id": None}

        campo_monto_ext = ft.TextField(
            label="Monto a aplicar (USD)",
            prefix_text="$ ",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
            visible=False,
            width=160,
        )
        texto_saldo_ext = ft.Text("", size=12, color=ft.Colors.GREEN_700,
                                   weight="bold", visible=False)
        btn_aplicar_ext = ft.ElevatedButton(
            "Aplicar saldo",
            icon=ft.Icons.CHECK,
            bgcolor=ft.Colors.TEAL_700, color=ft.Colors.WHITE,
            visible=False,
        )

        def buscar(evento):
            termino = campo_busqueda.value.strip()
            if len(termino) < 2:
                lista_resultados.controls = [texto_sin_resultados]
                lista_resultados.update()
                return

            sesion = SesionLocal()
            try:
                from database.models import Huesped as HM
                resultados = (
                    sesion.query(HM)
                    .filter(
                        (HM.documento.ilike(f"%{termino}%")) |
                        (HM.nombre.ilike(f"%{termino}%"))    |
                        (HM.apellido.ilike(f"%{termino}%"))
                    )
                    .limit(8)
                    .all()
                )

                if not resultados:
                    lista_resultados.controls = [
                        ft.Text("Sin resultados", size=12,
                                color=ft.Colors.GREY_400, italic=True)
                    ]
                else:
                    filas = []
                    for h in resultados:
                        saldo = self._saldo_real_huesped(sesion, h.id)
                        filas.append(ft.Container(
                            content=ft.Row([
                                ft.Column([
                                    ft.Text(h.nombre_completo, size=12,
                                            weight="bold"),
                                    ft.Text(f"Doc: {h.documento}", size=10,
                                            color=ft.Colors.GREY_600),
                                ], spacing=1, expand=True),
                                ft.Text(
                                    f"${saldo:.2f}",
                                    size=13, weight="bold",
                                    color=ft.Colors.GREEN_700 if saldo > 0.01
                                    else ft.Colors.GREY_400,
                                ),
                                ft.IconButton(
                                    ft.Icons.ARROW_FORWARD_IOS,
                                    icon_size=14,
                                    disabled=saldo <= 0.01,
                                    tooltip="Seleccionar este huésped",
                                    on_click=lambda _, hid=h.id,
                                                    nombre=h.nombre_completo,
                                                    s=saldo: seleccionar_huesped(
                                                        hid, nombre, s
                                                    ),
                                ),
                            ], spacing=6,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.symmetric(horizontal=10, vertical=7),
                            bgcolor=ft.Colors.WHITE,
                            border_radius=8,
                            border=ft.border.all(1, ft.Colors.GREY_100),
                        ))
                    lista_resultados.controls = filas
            finally:
                sesion.close()
            lista_resultados.update()

        def seleccionar_huesped(hid: int, nombre: str, saldo: float):
            seleccion["huesped_id"] = hid
            seleccion["nombre"]     = nombre
            seleccion["saldo"]      = saldo

            pendiente = self._pendiente()
            monto_sug = round(min(saldo, max(pendiente, 0)), 2)

            campo_monto_ext.value   = f"{monto_sug:.2f}"
            campo_monto_ext.visible = True
            texto_saldo_ext.value   = (
                f"Saldo disponible de {nombre}: ${saldo:.2f}"
            )
            texto_saldo_ext.visible = True
            btn_aplicar_ext.visible = True
            self.pagina.update()

        def confirmar_aplicacion(evento):
            hid    = seleccion["huesped_id"]
            nombre = seleccion["nombre"]
            saldo  = seleccion["saldo"]
            if not hid:
                return
            try:
                monto = round(float(campo_monto_ext.value or 0), 2)
            except ValueError:
                return
            if monto <= 0 or monto > saldo + 0.01:
                campo_monto_ext.error_text = (
                    f"Máximo disponible: ${saldo:.2f}"
                )
                campo_monto_ext.update()
                return

            tasa = self.config.tasa_cambio
            self.pagos_sesion.append({
                "metodo":           MetodoPago.SALDO_FAVOR,
                "monto_usd":        monto,
                "monto_bs":         a_bs(monto, tasa),
                "referencia":       "",
                "etiqueta":         f"Saldo a Favor ({nombre})",
                "color":            ft.Colors.TEAL_700,
                "icono":            ft.Icons.PERSON_PIN,
                "visualizacion":    f"${monto:.2f}",
                "es_saldo_favor":   True,
                "huesped_externo_id": hid,
                "huesped_externo_nombre": nombre,
                "descripcion_extra": (
                    f"Saldo aplicado del huésped {nombre} "
                    f"(doc: {seleccion.get('doc', '—')}) "
                    f"a esta cuenta"
                ),
            })
            self.pagina.close(modal_buscador)
            self.refrescar_interfaz()

        btn_aplicar_ext.on_click = confirmar_aplicacion
        campo_busqueda.on_change = buscar

        modal_buscador = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.PERSON_SEARCH, color=ft.Colors.TEAL_700),
                ft.Text("Aplicar saldo de otro huésped", weight="bold"),
            ], spacing=8),
            content=ft.Container(
                content=ft.Column([
                    campo_busqueda,
                    ft.Container(
                        content=lista_resultados,
                        height=180,
                        border=ft.border.all(1, ft.Colors.GREY_200),
                        border_radius=8,
                        padding=8,
                    ),
                    ft.Divider(),
                    texto_saldo_ext,
                    ft.Row([campo_monto_ext, btn_aplicar_ext],
                           spacing=10,
                           alignment=ft.MainAxisAlignment.START),
                ], spacing=10, tight=True),
                width=420,
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.pagina.close(modal_buscador),
                ),
            ],
        )
        self.pagina.open(modal_buscador)

    def finalizar_cobro(self, evento):
        """
        Graba los pagos, crea la TransaccionCobro, cierra las líneas seleccionadas
        y, si hubo pago parcial, crea una nueva LineaCuenta SALDO_PENDIENTE.
        Todo en una única transacción atómica.
        """
        if not self.pagos_sesion:
            return

        sesion = SesionLocal()
        try:
            caja = sesion.query(Caja).first()
            if not caja:
                raise Exception("No se encontró el registro de caja.")

            tasa             = self.config.tasa_cambio
            total_pagado_usd = sum(p["monto_usd"] for p in self.pagos_sesion)
            pendiente        = self._pendiente()   # >0 pago parcial, <0 sobrante

            # ── 1. Registrar pagos y actualizar caja ─────────────────────────
            estadia_bd_cobro = sesion.get(Estadia, self.id_estadia)
            for pago in self.pagos_sesion:
                descripcion_pago = pago.get(
                    "descripcion_extra", "Cobro de factura"
                )
                sesion.add(Pago(
                    estadia_id    = self.id_estadia,
                    monto_usd     = pago["monto_usd"],
                    monto_bs      = pago["monto_bs"],
                    tasa_cambio   = tasa,
                    metodo        = pago["metodo"],
                    referencia    = pago["referencia"] or "—",
                    descripcion   = descripcion_pago,
                    creado_en     = datetime.now(),
                    es_devolucion = False,
                ))
                if pago.get("es_saldo_favor"):
                    monto_sf = pago["monto_usd"]
                    huesped_ext_id = pago.get("huesped_externo_id")
                    nombre_ext     = pago.get("huesped_externo_nombre", "")

                    if huesped_ext_id:
                        # ── Saldo de huésped externo ──────────────────────
                        # 1. Descontar de estadías activas del huésped externo primero
                        from sqlalchemy.orm import selectinload as _sl2
                        estadias_ext = (
                            sesion.query(Estadia)
                            .options(_sl2(Estadia.huespedes))
                            .filter(
                                Estadia.activa       == True,
                                Estadia.id           != self.id_estadia,
                                Estadia.deposito_usd >  0,
                            )
                            .all()
                        )
                        restante = monto_sf
                        for est_ext in estadias_ext:
                            if not any(h.id == huesped_ext_id
                                       for h in est_ext.huespedes):
                                continue
                            descuento = min(restante,
                                           est_ext.deposito_usd or 0.0)
                            est_ext.deposito_usd = max(
                                0.0,
                                (est_ext.deposito_usd or 0.0) - descuento
                            )
                            restante = round(restante - descuento, 2)
                            if restante <= 0.01:
                                break
                        # 2. Si queda algo, descontar del crédito persistente
                        if restante > 0.01:
                            huesped_ext = sesion.get(Huesped, huesped_ext_id)
                            if huesped_ext:
                                huesped_ext.credito_usd = max(
                                    0.0,
                                    (huesped_ext.credito_usd or 0.0) - restante
                                )
                        # Actualizar descripción con trazabilidad
                        pago["descripcion_extra"] = (
                            f"Saldo aplicado del huésped {nombre_ext} "
                            f"a Hab. de estadía #{self.id_estadia}"
                        )
                    else:
                        # ── Saldo propio de la estadía actual ─────────────
                        if estadia_bd_cobro:
                            estadia_bd_cobro.deposito_usd = max(
                                0.0,
                                (estadia_bd_cobro.deposito_usd or 0.0) - monto_sf
                            )
                            self.saldo_favor_disponible = (
                                estadia_bd_cobro.deposito_usd
                            )
                elif pago["metodo"] in [
                    MetodoPago.CASH_USD, MetodoPago.ZELLE, MetodoPago.DEBIT_CARD
                ]:
                    caja.saldo_principal_usd += pago["monto_usd"]
                else:
                    caja.saldo_principal_bs  += pago["monto_bs"]

            # ── 2. Crear TransaccionCobro ─────────────────────────────────────
            saldo_pendiente_tx = max(0.0, round(pendiente, 2))
            transaccion = TransaccionCobro(
                estadia_id         = self.id_estadia,
                total_seleccionado = self.total_a_pagar,
                total_pagado       = round(total_pagado_usd, 2),
                saldo_pendiente    = saldo_pendiente_tx,
                creado_en          = datetime.now(),
            )
            sesion.add(transaccion)
            sesion.flush()   # obtener transaccion.id

            # ── 3. Marcar líneas seleccionadas como canceladas ────────────────
            for linea_id in self.lineas_ids:
                linea = sesion.get(LineaCuenta, linea_id)
                if linea:
                    linea.cancelada      = True
                    linea.transaccion_id = transaccion.id

            # ── 4. Pago parcial → crear LineaCuenta SALDO_PENDIENTE ───────────
            if saldo_pendiente_tx > 0.01:
                conceptos = []
                for linea_id in self.lineas_ids:
                    linea = sesion.get(LineaCuenta, linea_id)
                    if linea:
                        conceptos.append(linea.concepto)
                resumen = "; ".join(conceptos[:3])
                if len(conceptos) > 3:
                    resumen += f" (+{len(conceptos)-3} más)"

                sesion.add(LineaCuenta(
                    estadia_id     = self.id_estadia,
                    transaccion_id = transaccion.id,
                    tipo           = TipoLinea.SALDO_PENDIENTE,
                    concepto       = (
                        f"Saldo pendiente de cobro — {resumen}"
                    ),
                    monto_usd      = saldo_pendiente_tx,
                    cancelada      = False,
                    creado_en      = datetime.now(),
                ))

            # ── 5. Gestionar sobrante (el cliente pagó de más) ───────────────
            elif pendiente < -0.01:
                monto_sobrante = abs(pendiente)
                ultimo_metodo  = (
                    self.pagos_sesion[-1]["metodo"] if self.pagos_sesion
                    else MetodoPago.CASH_USD
                )

                if (self.radio_tipo_sobrante
                        and self.radio_tipo_sobrante.value == "credito"):
                    estadia_bd = sesion.get(Estadia, self.id_estadia)
                    if estadia_bd and estadia_bd.huespedes:
                        huesped = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                        if huesped:
                            huesped.credito_usd = (
                                (huesped.credito_usd or 0.0) + monto_sobrante
                            )
                    if estadia_bd:
                        estadia_bd.deposito_usd += monto_sobrante

                    sesion.add(Pago(
                        estadia_id    = self.id_estadia,
                        monto_usd     = monto_sobrante,
                        monto_bs      = a_bs(monto_sobrante, tasa),
                        es_devolucion = True,
                        metodo        = ultimo_metodo,
                        tasa_cambio   = tasa,
                        descripcion   = "Sobrante registrado como saldo a favor",
                        creado_en     = datetime.now(),
                    ))

                else:
                    c_ppal, c_chica, c_ppal_bs, c_chica_bs = (
                        self.campos_desglose_vuelto
                    )
                    val_ppal     = float(c_ppal.value    or 0)
                    val_chica    = float(c_chica.value   or 0)
                    val_ppal_bs  = float(c_ppal_bs.value or 0)
                    val_chica_bs = float(c_chica_bs.value or 0)

                    if caja.saldo_principal_usd < val_ppal:
                        raise Exception("Fondos insuficientes — Caja Principal $")
                    if caja.caja_chica_usd < val_chica:
                        raise Exception("Fondos insuficientes — Caja Chica $")
                    if caja.saldo_principal_bs < val_ppal_bs:
                        raise Exception("Fondos insuficientes — Caja Principal Bs")
                    if caja.caja_chica_bs < val_chica_bs:
                        raise Exception("Fondos insuficientes — Caja Chica Bs")

                    caja.saldo_principal_usd -= val_ppal
                    caja.caja_chica_usd      -= val_chica
                    caja.saldo_principal_bs  -= val_ppal_bs
                    caja.caja_chica_bs       -= val_chica_bs

                    sesion.add(Pago(
                        estadia_id    = self.id_estadia,
                        monto_usd     = monto_sobrante,
                        monto_bs      = a_bs(monto_sobrante, tasa),
                        es_devolucion = True,
                        metodo        = ultimo_metodo,
                        tasa_cambio   = tasa,
                        descripcion   = (
                            f"Vuelto — P$:{val_ppal:.2f} | C$:{val_chica:.2f} | "
                            f"PBs:{val_ppal_bs:.2f} | CBs:{val_chica_bs:.2f}"
                        ),
                        creado_en     = datetime.now(),
                    ))

            sesion.commit()
            self.pagina.close(self.dialogo)
            self.pagina.open(ft.SnackBar(
                ft.Text(
                    "Cobro registrado correctamente"
                    if saldo_pendiente_tx <= 0.01
                    else f"Cobro parcial — Quedan ${saldo_pendiente_tx:.2f} pendientes"
                ),
                bgcolor=(
                    ft.Colors.GREEN_700 if saldo_pendiente_tx <= 0.01
                    else ft.Colors.BLUE_700
                ),
            ))
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error al registrar el pago: {error}"),
                bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()

    def mostrar(self):
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)