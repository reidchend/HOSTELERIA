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

    SALDO A FAVOR — fuente única: Huesped.credito_usd
    ─────────────────────────────────────────────────
    El saldo a favor vive SOLO en Huesped.credito_usd.
    Estadia.deposito_usd ya NO se usa para saldo a favor; se ignora aquí.

    · Saldo propio:    credito_usd del titular de ESTA estadía.
    · Saldo externo:   credito_usd de cualquier otro huésped registrado.

    PAGO PARCIAL:
      Si el cliente paga menos del total seleccionado se crea una
      TransaccionCobro con saldo_pendiente > 0 y una nueva LineaCuenta
      SALDO_PENDIENTE cobrable después.

    SOBRANTE:
      Si el cliente paga de más, el sobrante se acredita directamente en
      Huesped.credito_usd (opción "saldo a favor") o se entrega en físico.
    """

    def __init__(self, pagina, estadia, total_a_pagar, al_completar, lineas_ids=None):
        self.pagina        = pagina
        self.estadia       = estadia
        self.id_estadia    = estadia.id
        self.total_a_pagar = total_a_pagar
        self.al_completar  = al_completar
        self.lineas_ids    = lineas_ids or []
        self.dialogo       = None

        sesion = SesionLocal()
        try:
            self.config = leer_config_financiera(sesion)
            self.saldo_favor_disponible = self._leer_credito_titular(sesion)
        finally:
            sesion.close()

        self.pagos_sesion = []

        self.columna_saldo        = ft.Column(spacing=6)
        self.columna_pagos_sesion = ft.Column(spacing=6)
        self.area_formulario      = ft.Column(spacing=8)
        self.seccion_sobrante     = ft.Container(visible=False)
        self.btn_finalizar        = None
        self.radio_tipo_sobrante    = None
        self.campos_desglose_vuelto = None
        self.monto_sobrante_usd     = 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS DE SALDO  —  fuente única: Huesped.credito_usd
    # ══════════════════════════════════════════════════════════════════════════

    def _leer_credito_titular(self, sesion):
        """Devuelve el credito_usd del titular de esta estadía."""
        estadia_bd = (
            sesion.query(Estadia)
            .options(selectinload(Estadia.huespedes))
            .filter(Estadia.id == self.id_estadia)
            .first()
        )
        if not estadia_bd or not estadia_bd.huespedes:
            return 0.0
        titular = sesion.get(Huesped, estadia_bd.huespedes[0].id)
        return round(titular.credito_usd or 0.0, 2) if titular else 0.0

    def _leer_credito_huesped(self, sesion, huesped_id):
        """Devuelve el credito_usd de cualquier huésped por id."""
        h = sesion.get(Huesped, huesped_id)
        return round(h.credito_usd or 0.0, 2) if h else 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS
    # ══════════════════════════════════════════════════════════════════════════

    def _cargar_lineas(self, sesion):
        if not self.lineas_ids:
            return []
        return sesion.query(LineaCuenta).filter(LineaCuenta.id.in_(self.lineas_ids)).all()

    def _datos_para_panel(self, sesion):
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
            "estadia":       estadia,
            "habitacion":    estadia.habitacion,
            "titular":       estadia.huespedes[0] if estadia.huespedes else None,
            "pagos_previos": [p for p in estadia.pagos if not p.es_devolucion],
        }

    # ══════════════════════════════════════════════════════════════════════════
    # SALDO EN TIEMPO REAL
    # ══════════════════════════════════════════════════════════════════════════

    def _pendiente(self):
        abonado = sum(p["monto_usd"] for p in self.pagos_sesion)
        return round(self.total_a_pagar - abonado, 2)

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN DE LA UI
    # ══════════════════════════════════════════════════════════════════════════

    def construir(self):
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
                    border=ft.border.only(right=ft.border.BorderSide(1, ft.Colors.GREY_200)),
                    padding=18,
                ),
                ft.Container(content=self._panel_cobro(), expand=True, padding=18),
            ],
            spacing=0, expand=True,
        )

        self.dialogo = ft.AlertDialog(
            title=self._encabezado(datos),
            content=ft.Container(content=cuerpo, width=880, height=540),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                self.btn_finalizar,
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        return self.dialogo

    def _encabezado(self, datos):
        titular = datos["titular"]
        return ft.Row(controls=[
            ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE_800, size=22),
            ft.Column(controls=[
                ft.Text(f"Cobro — Habitación {datos['habitacion'].numero}", weight="bold", size=15),
                ft.Text(titular.nombre_completo if titular else "Huésped", size=11, color=ft.Colors.GREY_600),
            ], spacing=1),
            ft.Container(expand=True),
            ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(ft.Icons.CURRENCY_EXCHANGE, size=13, color=ft.Colors.GREY_600),
                    ft.Text(f"Tasa: Bs. {self.config.tasa_cambio:,.2f}", size=12, color=ft.Colors.GREY_700),
                ], spacing=5),
                bgcolor=ft.Colors.GREY_100,
                padding=ft.padding.symmetric(horizontal=12, vertical=5),
                border_radius=20,
            ),
        ], spacing=10)

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL IZQUIERDO — DETALLE DE LÍNEAS
    # ══════════════════════════════════════════════════════════════════════════

    def _panel_factura(self, datos, lineas):
        tasa = self.config.tasa_cambio
        filas_lineas = []

        for linea in lineas:
            if linea.tipo == TipoLinea.HOSPEDAJE:
                icono, color_ico, etiq, color_t = ft.Icons.BED_OUTLINED, ft.Colors.BLUE_700, "Hospedaje", ft.Colors.BLUE_700
            elif linea.tipo == TipoLinea.CARGO_EXTRA:
                icono, color_ico, etiq, color_t = ft.Icons.ROOM_SERVICE, ft.Colors.ORANGE_700, "Servicio (c/IVA)", ft.Colors.ORANGE_700
            else:
                icono, color_ico, etiq, color_t = ft.Icons.PENDING_ACTIONS, ft.Colors.RED_700, "Saldo pendiente", ft.Colors.RED_700

            filas_lineas.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(icono, size=14, color=color_ico),
                    ft.Column(controls=[
                        ft.Text(linea.concepto, size=11, color=ft.Colors.BLACK87),
                        ft.Container(
                            content=ft.Text(etiq, size=9, color=color_t),
                            bgcolor=ft.Colors.with_opacity(0.1, color_t),
                            padding=ft.padding.symmetric(horizontal=5, vertical=1),
                            border_radius=4,
                        ),
                    ], spacing=2, expand=True),
                    ft.Column(controls=[
                        ft.Text(f"${linea.monto_usd:.2f}", size=12, weight="bold", text_align=ft.TextAlign.RIGHT),
                        ft.Text(f"Bs.{a_bs(linea.monto_usd, tasa):,.0f}", size=9, color=ft.Colors.GREY_500, text_align=ft.TextAlign.RIGHT),
                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                ], spacing=8),
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                bgcolor=ft.Colors.WHITE, border_radius=7,
                border=ft.border.all(1, ft.Colors.GREY_100),
            ))

        tiene_hosp   = any(l.tipo == TipoLinea.HOSPEDAJE   for l in lineas)
        tiene_extras = any(l.tipo == TipoLinea.CARGO_EXTRA for l in lineas)
        nota_iva = []
        if tiene_hosp:   nota_iva.append("🏨 Hospedaje: precio sin IVA")
        if tiene_extras: nota_iva.append("🍽 Servicios: precio con IVA incluido")

        self.columna_saldo.controls = self._filas_saldo()

        return ft.Column(controls=[ft.Column(controls=[
            ft.Text("CONCEPTOS A COBRAR", size=9, weight="bold", color=ft.Colors.BLUE_GREY_400),
            ft.Column(controls=filas_lineas, spacing=5),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            ft.Column(controls=[ft.Text(n, size=9, color=ft.Colors.GREY_500, italic=True) for n in nota_iva], spacing=2) if nota_iva else ft.Container(),
            ft.Container(
                content=ft.Row(controls=[
                    ft.Text("TOTAL A COBRAR:", size=13, weight="bold", expand=True),
                    ft.Column(controls=[
                        ft.Text(f"${self.total_a_pagar:.2f}", size=18, weight="bold", color=ft.Colors.BLUE_900),
                        ft.Text(f"Bs. {a_bs(self.total_a_pagar, tasa):,.2f}", size=10, color=ft.Colors.GREY_600, text_align=ft.TextAlign.RIGHT),
                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
                ]),
                bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=8,
            ),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            self.columna_saldo,
        ], spacing=8)], scroll=ft.ScrollMode.AUTO, spacing=10, expand=True)

    def _filas_saldo(self):
        pendiente = self._pendiente()
        abonado   = sum(p["monto_usd"] for p in self.pagos_sesion)
        tasa      = self.config.tasa_cambio
        filas     = []

        if self.pagos_sesion:
            filas.append(ft.Row(controls=[
                ft.Text("Abonado ahora:", size=11, expand=True, color=ft.Colors.GREEN_700),
                ft.Column(controls=[
                    ft.Text(f"${abonado:.2f}", size=12, weight="bold", color=ft.Colors.GREEN_700, text_align=ft.TextAlign.RIGHT),
                    ft.Text(f"Bs. {a_bs(abonado, tasa):,.2f}", size=10, color=ft.Colors.GREEN_600, text_align=ft.TextAlign.RIGHT),
                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
            ]))

        if pendiente > 0.01:
            filas.append(ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.PENDING, color=ft.Colors.RED_700, size=15),
                        ft.Text("PENDIENTE:", size=12, weight="bold", color=ft.Colors.RED_700, expand=True),
                        ft.Text(f"${pendiente:.2f}", size=15, weight="bold", color=ft.Colors.RED_700),
                    ]),
                    ft.Text(f"Bs. {a_bs(pendiente, tasa):,.2f}", size=11, color=ft.Colors.RED_400, text_align=ft.TextAlign.RIGHT),
                    ft.Text("⚠ La diferencia quedará como saldo pendiente.", size=9, color=ft.Colors.RED_400, italic=True) if self.pagos_sesion else ft.Container(),
                ], spacing=3),
                bgcolor=ft.Colors.RED_50, padding=10, border_radius=8,
            ))
        elif pendiente < -0.01:
            sobrante = abs(pendiente)
            filas.append(ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.ARROW_CIRCLE_UP, color=ft.Colors.ORANGE_700, size=15),
                        ft.Text("SOBRANTE:", size=12, weight="bold", color=ft.Colors.ORANGE_700, expand=True),
                        ft.Text(f"${sobrante:.2f}", size=15, weight="bold", color=ft.Colors.ORANGE_700),
                    ]),
                    ft.Text(f"Bs. {a_bs(sobrante, tasa):,.2f}", size=11, color=ft.Colors.ORANGE_400, text_align=ft.TextAlign.RIGHT),
                ], spacing=3),
                bgcolor=ft.Colors.ORANGE_50, padding=10, border_radius=8,
            ))
        else:
            filas.append(ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700, size=16),
                    ft.Text("CUENTA SALDADA", size=12, weight="bold", color=ft.Colors.GREEN_700),
                ], spacing=6),
                bgcolor=ft.Colors.GREEN_50, padding=10, border_radius=8,
            ))
        return filas

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL DERECHO
    # ══════════════════════════════════════════════════════════════════════════

    def _panel_cobro(self):
        self.area_formulario.controls = [
            ft.Container(
                content=ft.Text("← Selecciona un método para ingresar el pago", size=12, color=ft.Colors.GREY_500, italic=True),
                padding=ft.padding.symmetric(vertical=12),
            )
        ]

        botones = [
            ft.ElevatedButton(
                text=cfg["etiqueta"], icon=cfg["icono"],
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
            style=ft.ButtonStyle(color=ft.Colors.TEAL_700, side=ft.BorderSide(1.2, ft.Colors.TEAL_300)),
            height=38,
            on_click=lambda _: self._abrir_buscador_huesped_externo(),
        )

        return ft.Column(
            controls=[
                ft.Text("MÉTODO DE PAGO", size=9, weight="bold", color=ft.Colors.BLUE_GREY_400),
                ft.Row(controls=botones, wrap=True, spacing=8, run_spacing=8),
                ft.Row(controls=[btn_saldo_favor, btn_saldo_externo], spacing=8, wrap=True),
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                self.area_formulario,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Row(controls=[
                    ft.Icon(ft.Icons.RECEIPT, size=13, color=ft.Colors.BLUE_GREY_300),
                    ft.Text("PAGOS DE ESTA SESIÓN", size=9, weight="bold", color=ft.Colors.BLUE_GREY_300),
                ], spacing=5),
                self.columna_pagos_sesion,
                self.seccion_sobrante,
            ],
            spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # SELECCIÓN DE MÉTODO
    # ══════════════════════════════════════════════════════════════════════════

    def seleccionar_metodo(self, metodo):
        cfg = CONFIGURACION_METODOS[metodo]
        es_bs = cfg["es_bs"]
        necesita_referencia = metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS]
        tasa = self.config.tasa_cambio

        pendiente = self._pendiente()
        valor_sug = f"{a_bs(pendiente, tasa):.2f}" if (pendiente > 0 and es_bs) else (f"{pendiente:.2f}" if pendiente > 0 else "0.00")

        campo_monto = ft.TextField(
            label=f"Monto recibido ({'Bs.' if es_bs else 'USD'})",
            value=valor_sug,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
            autofocus=True, expand=True,
        )
        campo_ref = ft.TextField(label="Nro. Referencia / Confirmación", visible=necesita_referencia, expand=True)

        def agregar(evento):
            try:
                valor = float(campo_monto.value.replace(",", ".") or 0)
                if valor <= 0:
                    campo_monto.error_text = "Ingrese un monto válido"
                    campo_monto.update()
                    return
                campo_monto.error_text = None
                monto_usd = a_usd(valor, tasa) if es_bs else valor
                monto_bs  = valor if es_bs else a_bs(valor, tasa)
                self.pagos_sesion.append({
                    "metodo": metodo, "monto_usd": monto_usd, "monto_bs": monto_bs,
                    "referencia": campo_ref.value.strip() if necesita_referencia else "",
                    "etiqueta": cfg["etiqueta"], "color": cfg["color"], "icono": cfg["icono"],
                    "visualizacion": f"Bs. {valor:,.2f}" if es_bs else f"${valor:.2f}",
                })
                self.refrescar_interfaz()
            except (ValueError, AttributeError):
                campo_monto.error_text = "Número inválido"
                campo_monto.update()

        self.area_formulario.controls = [
            ft.Container(
                content=ft.Column(controls=[
                    ft.Row(controls=[ft.Icon(cfg["icono"], color=cfg["color"], size=18), ft.Text(cfg["etiqueta"], weight="bold", color=cfg["color"], size=13)], spacing=6),
                    ft.Row(controls=[campo_monto, campo_ref] if necesita_referencia else [campo_monto], spacing=10),
                    ft.ElevatedButton("+ AGREGAR PAGO", bgcolor=cfg["color"], color=ft.Colors.WHITE, on_click=agregar, expand=True, height=40),
                ], spacing=10),
                padding=14,
                bgcolor=ft.Colors.with_opacity(0.04, cfg["color"]),
                border_radius=10,
                border=ft.border.all(1.5, ft.Colors.with_opacity(0.25, cfg["color"])),
            )
        ]
        self.pagina.update()

    def refrescar_interfaz(self):
        self.columna_saldo.controls = self._filas_saldo()
        self.columna_pagos_sesion.controls = [
            ft.Container(
                content=ft.Row(controls=[
                    ft.Icon(p["icono"], size=14, color=p["color"]),
                    ft.Text(p["etiqueta"], size=12, expand=True),
                    ft.Text(p["visualizacion"], size=12, weight="bold"),
                    ft.Text(f"  (${p['monto_usd']:.2f})", size=10, color=ft.Colors.GREY_600),
                    ft.IconButton(ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_size=15, icon_color=ft.Colors.RED_400,
                                  tooltip="Quitar este pago", on_click=lambda _, i=idx: self.quitar_pago(i)),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                bgcolor=ft.Colors.with_opacity(0.06, p["color"]), border_radius=7,
            )
            for idx, p in enumerate(self.pagos_sesion)
        ]
        pendiente = self._pendiente()
        if pendiente < -0.01:
            self.mostrar_seccion_sobrante(abs(pendiente))
            self.btn_finalizar.disabled = False
            self.btn_finalizar.bgcolor  = ft.Colors.ORANGE_700
            self.btn_finalizar.text     = "CONFIRMAR Y GESTIONAR SOBRANTE"
        elif self.pagos_sesion:
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled   = False
            self.btn_finalizar.bgcolor    = ft.Colors.GREEN_700 if abs(pendiente) <= 0.01 else ft.Colors.BLUE_700
            self.btn_finalizar.text       = "FINALIZAR COBRO" if abs(pendiente) <= 0.01 else f"COBRAR PARCIAL (quedan ${pendiente:.2f})"
        else:
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled   = True
            self.btn_finalizar.bgcolor    = ft.Colors.GREY_400
            self.btn_finalizar.text       = "FINALIZAR COBRO"
        self.pagina.update()

    def quitar_pago(self, indice):
        self.pagos_sesion.pop(indice)
        self.refrescar_interfaz()

    # ══════════════════════════════════════════════════════════════════════════
    # SALDO A FAVOR PROPIO  —  fuente: Huesped.credito_usd del titular
    # ══════════════════════════════════════════════════════════════════════════

    def _aplicar_saldo_favor(self):
        pendiente  = self._pendiente()
        disponible = self.saldo_favor_disponible
        if disponible <= 0.01 or pendiente <= 0.01:
            return
        monto_aplicar = round(min(disponible, pendiente), 2)
        tasa          = self.config.tasa_cambio
        self.pagos_sesion.append({
            "metodo":         MetodoPago.SALDO_FAVOR,
            "monto_usd":      monto_aplicar,
            "monto_bs":       a_bs(monto_aplicar, tasa),
            "referencia":     "",
            "etiqueta":       f"Saldo a Favor del titular (${monto_aplicar:.2f})",
            "color":          ft.Colors.GREEN_800,
            "icono":          ft.Icons.ACCOUNT_BALANCE_WALLET,
            "visualizacion":  f"${monto_aplicar:.2f}",
            "es_saldo_favor": True,
            # Sin huesped_externo_id  →  descuenta del titular de esta estadía
        })
        self.saldo_favor_disponible = round(disponible - monto_aplicar, 2)
        self.refrescar_interfaz()

    # ══════════════════════════════════════════════════════════════════════════
    # BUSCADOR DE SALDO EXTERNO  —  lista + búsqueda
    # ══════════════════════════════════════════════════════════════════════════

    def _abrir_buscador_huesped_externo(self):
        """
        Muestra el buscador de huéspedes DENTRO de self.area_formulario,
        exactamente como lo hace seleccionar_metodo() con los formularios
        de pago normales. Así nunca se abre un segundo diálogo y la pila
        de Flet 0.28.3 permanece intacta con un único AlertDialog activo.

        Flujo de pantallas dentro de area_formulario:
          Pantalla A → campo de búsqueda + lista de huéspedes con saldo
          Pantalla B → confirmar el monto a aplicar del huésped elegido
        Al confirmar: descuenta la BD, agrega a pagos_sesion y llama
        refrescar_interfaz() — todo sin tocar page.open/close.
        """

        # ── Widgets de la Pantalla A ──────────────────────────────────────────
        lista_col      = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=200)
        campo_busqueda = ft.TextField(
            label="Documento o nombre",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            autofocus=True,
        )

        def _cargar(termino=""):
            """Consulta huéspedes con crédito y puebla lista_col."""
            sesion = SesionLocal()
            try:
                q = sesion.query(Huesped).filter(Huesped.credito_usd > 0)
                if termino:
                    q = q.filter(
                        (Huesped.documento.ilike(f"%{termino}%")) |
                        (Huesped.nombre.ilike(f"%{termino}%"))    |
                        (Huesped.apellido.ilike(f"%{termino}%"))
                    )
                huespedes = q.order_by(Huesped.credito_usd.desc()).limit(20).all()
                lista_col.controls = (
                    [_fila(h) for h in huespedes]
                    if huespedes else
                    [ft.Text("Sin huéspedes con saldo a favor.",
                             size=11, color=ft.Colors.GREY_400, italic=True)]
                )
            finally:
                sesion.close()
            # area_formulario ya está montado en el árbol del diálogo activo
            self.area_formulario.update()

        def _fila(h):
            """Una fila de la lista: nombre, doc, saldo y botón Usar."""
            hid    = h.id
            doc    = h.documento
            nombre = h.nombre_completo
            saldo  = round(h.credito_usd or 0.0, 2)
            return ft.Container(
                content=ft.Row([
                    ft.Column([
                        ft.Text(nombre, size=11, weight="bold"),
                        ft.Text(f"Doc: {doc}", size=10, color=ft.Colors.GREY_600),
                    ], spacing=1, expand=True),
                    ft.Container(
                        content=ft.Text(f"${saldo:.2f}", size=12,
                                        weight="bold", color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.GREEN_700,
                        padding=ft.padding.symmetric(horizontal=8, vertical=3),
                        border_radius=6,
                    ),
                    ft.ElevatedButton(
                        "Usar",
                        height=30,
                        style=ft.ButtonStyle(
                            color=ft.Colors.TEAL_700,
                            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.TEAL_700),
                            side=ft.BorderSide(1, ft.Colors.TEAL_300),
                            shape=ft.RoundedRectangleBorder(radius=6),
                        ),
                        on_click=lambda _, i=hid, d=doc, n=nombre, s=saldo:
                            _mostrar_pantalla_b(i, d, n, s),
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(horizontal=8, vertical=5),
                bgcolor=ft.Colors.WHITE, border_radius=7,
                border=ft.border.all(1, ft.Colors.GREY_100),
            )

        def _mostrar_pantalla_a():
            """Renderiza la pantalla de búsqueda en area_formulario."""
            campo_busqueda.on_change = lambda _: _cargar(campo_busqueda.value.strip())
            self.area_formulario.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.PERSON_SEARCH,
                                    color=ft.Colors.TEAL_700, size=16),
                            ft.Text("Saldo de otro huésped", size=13,
                                    weight="bold", color=ft.Colors.TEAL_700),
                        ], spacing=6),
                        campo_busqueda,
                        ft.Container(
                            content=lista_col,
                            border=ft.border.all(1, ft.Colors.GREY_200),
                            border_radius=8, padding=6,
                        ),
                        # Botón cancelar: vuelve al estado vacío del área
                        ft.TextButton(
                            "✕  Cancelar búsqueda",
                            style=ft.ButtonStyle(color=ft.Colors.GREY_500),
                            on_click=lambda _: _cancelar(),
                        ),
                    ], spacing=8),
                    bgcolor=ft.Colors.TEAL_50, padding=12, border_radius=10,
                    border=ft.border.all(1, ft.Colors.TEAL_100),
                )
            ]
            self.area_formulario.update()
            _cargar()   # carga inicial sin filtro

        # ── Pantalla B — confirmar monto ──────────────────────────────────────
        def _mostrar_pantalla_b(hid, doc, nombre, credito):
            pendiente   = self._pendiente()
            monto_sug   = round(min(credito, max(pendiente, 0.0)), 2)

            campo_monto = ft.TextField(
                label="Monto a aplicar",
                value=f"{monto_sug:.2f}",
                suffix_text="USD",
                keyboard_type=ft.KeyboardType.NUMBER,
                text_align=ft.TextAlign.RIGHT,
                width=180,
                autofocus=True,
            )
            txt_error = ft.Text("", color=ft.Colors.RED_700, size=11)

            def _aplicar(_):
                # 1. Validar
                try:
                    monto = round(
                        float((campo_monto.value or "")
                              .replace("$", "").replace(",", ".").strip()), 2
                    )
                except (ValueError, AttributeError):
                    txt_error.value = "Número inválido"
                    txt_error.update()
                    return
                if monto <= 0:
                    txt_error.value = "El monto debe ser mayor a 0"
                    txt_error.update()
                    return
                if monto > credito + 0.01:
                    txt_error.value = f"Máximo disponible: ${credito:.2f}"
                    txt_error.update()
                    return

                # 2. Descontar crédito en la BD de forma inmediata y atómica.
                #    Se hace aquí — no en finalizar_cobro — para que el
                #    crédito quede reservado aunque el usuario cierre el modal
                #    de pagos sin finalizar. finalizar_cobro respeta la bandera
                #    ya_descontado_en_bd y no vuelve a tocarlo.
                sesion = SesionLocal()
                try:
                    h_ext = sesion.get(Huesped, hid)
                    if not h_ext:
                        txt_error.value = "Huésped no encontrado"
                        txt_error.update()
                        return
                    credito_real = h_ext.credito_usd or 0.0
                    if monto > credito_real + 0.01:
                        txt_error.value = f"Saldo actual: ${credito_real:.2f}"
                        txt_error.update()
                        return
                    h_ext.credito_usd = max(0.0, credito_real - monto)
                    sesion.commit()
                except Exception as exc:
                    sesion.rollback()
                    txt_error.value = f"Error BD: {exc}"
                    txt_error.update()
                    return
                finally:
                    sesion.close()

                # 3. Agregar a pagos_sesion con bandera ya_descontado_en_bd
                tasa = self.config.tasa_cambio
                self.pagos_sesion.append({
                    "metodo":                 MetodoPago.SALDO_FAVOR,
                    "monto_usd":              monto,
                    "monto_bs":               a_bs(monto, tasa),
                    "referencia":             "",
                    "etiqueta":               f"Saldo de {nombre}",
                    "color":                  ft.Colors.TEAL_700,
                    "icono":                  ft.Icons.PERSON_PIN,
                    "visualizacion":          f"${monto:.2f}",
                    "es_saldo_favor":         True,
                    "ya_descontado_en_bd":    True,
                    "huesped_externo_id":     hid,
                    "huesped_externo_nombre": nombre,
                    "huesped_externo_doc":    doc,
                    "descripcion_extra": (
                        f"Saldo de {nombre} (doc: {doc}) "
                        f"aplicado a estadía #{self.id_estadia}"
                    ),
                })

                # 4. Limpiar area_formulario y refrescar el panel de pagos.
                #    Al no haber segundo diálogo, refrescar_interfaz() opera
                #    directamente sobre el único diálogo abierto — funciona.
                _cancelar()
                self.refrescar_interfaz()

            self.area_formulario.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.PERSON, color=ft.Colors.TEAL_700, size=15),
                            ft.Text(nombre, size=12, weight="bold"),
                        ], spacing=6),
                        ft.Text(f"Doc: {doc} · Crédito: ${credito:.2f}",
                                size=11, color=ft.Colors.GREY_600),
                        ft.Divider(height=4),
                        ft.Row([campo_monto], spacing=8),
                        txt_error,
                        ft.Row([
                            ft.TextButton(
                                "← Volver",
                                style=ft.ButtonStyle(color=ft.Colors.GREY_600),
                                on_click=lambda _: _mostrar_pantalla_a(),
                            ),
                            ft.ElevatedButton(
                                "Aplicar saldo",
                                icon=ft.Icons.CHECK,
                                bgcolor=ft.Colors.TEAL_700,
                                color=ft.Colors.WHITE,
                                on_click=_aplicar,
                            ),
                        ], spacing=10),
                    ], spacing=8),
                    bgcolor=ft.Colors.TEAL_50, padding=12, border_radius=10,
                    border=ft.border.all(1, ft.Colors.TEAL_100),
                )
            ]
            self.area_formulario.update()

        def _cancelar():
            """Devuelve area_formulario al estado de bienvenida."""
            self.area_formulario.controls = [
                ft.Container(
                    content=ft.Text(
                        "← Selecciona un método para ingresar el pago",
                        size=12, color=ft.Colors.GREY_500, italic=True,
                    ),
                    padding=ft.padding.symmetric(vertical=12),
                )
            ]
            self.area_formulario.update()

        # Iniciar directamente en la pantalla A
        _mostrar_pantalla_a()


    def mostrar_seccion_sobrante(self, sobrante_usd):
        tasa        = self.config.tasa_cambio
        sobrante_bs = a_bs(sobrante_usd, tasa)

        self.radio_tipo_sobrante = ft.RadioGroup(
            content=ft.Column(controls=[
                ft.Radio(value="credito", label=f"Dejar ${sobrante_usd:.2f} como saldo a favor del huésped  (Bs. {sobrante_bs:,.2f})"),
                ft.Radio(value="vuelto",  label="Entregar vuelto en este momento"),
            ]),
            value="credito",
        )

        c_ppal_usd  = ft.TextField(label="Caja Ppal. $", value=f"{sobrante_usd:.2f}", width=120, text_align=ft.TextAlign.RIGHT)
        c_chica_usd = ft.TextField(label="Caja Chica $", value="0.00",                width=120, text_align=ft.TextAlign.RIGHT)
        c_ppal_bs   = ft.TextField(label="Ppal. Bs",     value="0.00",                width=120, text_align=ft.TextAlign.RIGHT)
        c_chica_bs  = ft.TextField(label="Chica Bs",     value="0.00",                width=120, text_align=ft.TextAlign.RIGHT)
        txt_diff    = ft.Text("", size=11)

        self.campos_desglose_vuelto = (c_ppal_usd, c_chica_usd, c_ppal_bs, c_chica_bs)
        self.monto_sobrante_usd = sobrante_usd

        def validar(evento):
            try:
                total = float(c_ppal_usd.value or 0) + float(c_chica_usd.value or 0) + a_usd(float(c_ppal_bs.value or 0) + float(c_chica_bs.value or 0), tasa)
                diff = round(sobrante_usd - total, 2)
                txt_diff.value = "Distribución correcta" if abs(diff) < 0.02 else f"Diferencia: ${diff:.2f}"
                txt_diff.color = ft.Colors.GREEN_700 if abs(diff) < 0.02 else ft.Colors.RED_700
                self.pagina.update()
            except Exception:
                pass

        for c in self.campos_desglose_vuelto:
            c.on_change = validar

        desglose = ft.Column(controls=[
            ft.Text("Distribución del vuelto:", size=11, color=ft.Colors.GREY_700),
            ft.Row(controls=[c_ppal_usd, c_chica_usd, c_ppal_bs, c_chica_bs], spacing=8, wrap=True),
            txt_diff,
        ], spacing=6, visible=False)

        def cambiar_modo(evento):
            desglose.visible = (self.radio_tipo_sobrante.value == "vuelto")
            self.pagina.update()

        self.radio_tipo_sobrante.on_change = cambiar_modo
        self.seccion_sobrante.visible = True
        self.seccion_sobrante.content = ft.Container(
            content=ft.Column(controls=[
                ft.Row(controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.ORANGE_700, size=16),
                    ft.Text(f"Sobrante: ${sobrante_usd:.2f}  ·  Bs. {sobrante_bs:,.2f}", weight="bold", color=ft.Colors.ORANGE_700, size=13),
                ], spacing=6),
                self.radio_tipo_sobrante,
                desglose,
            ], spacing=10),
            bgcolor=ft.Colors.ORANGE_50, padding=14, border_radius=10,
            border=ft.border.all(1, ft.Colors.ORANGE_200),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PERSISTENCIA — TRANSACCIÓN FINAL
    # ══════════════════════════════════════════════════════════════════════════

    def finalizar_cobro(self, evento):
        """
        Todo en una transacción atómica.

        Saldo a favor propio (sin huesped_externo_id):
          Descuenta Huesped.credito_usd del titular de esta estadía.

        Saldo externo (con huesped_externo_id):
          Descuenta Huesped.credito_usd del huésped externo.

        Sobrante → "saldo a favor":
          Se acredita SOLO en Huesped.credito_usd del titular.
          Estadia.deposito_usd NO se toca.
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
            pendiente        = self._pendiente()

            estadia_bd = (
                sesion.query(Estadia)
                .options(selectinload(Estadia.huespedes))
                .filter(Estadia.id == self.id_estadia)
                .first()
            )

            # ── 1. Registrar pagos ─────────────────────────────────────────────
            for pago in self.pagos_sesion:
                sesion.add(Pago(
                    estadia_id    = self.id_estadia,
                    monto_usd     = pago["monto_usd"],
                    monto_bs      = pago["monto_bs"],
                    tasa_cambio   = tasa,
                    metodo        = pago["metodo"],
                    referencia    = pago.get("referencia") or "—",
                    descripcion   = pago.get("descripcion_extra", "Cobro de factura"),
                    creado_en     = datetime.now(),
                    es_devolucion = False,
                ))

                if pago.get("es_saldo_favor"):
                    monto_sf       = pago["monto_usd"]
                    huesped_ext_id = pago.get("huesped_externo_id")
                    doc_ext        = pago.get("huesped_externo_doc", "—")
                    nombre_ext     = pago.get("huesped_externo_nombre", "")

                    # Si ya_descontado_en_bd=True el crédito fue descontado
                    # en el momento de confirmar en el buscador — no tocar de nuevo.
                    if pago.get("ya_descontado_en_bd"):
                        pass   # solo registrar el Pago, nada más
                    elif huesped_ext_id:
                        # Descuenta del crédito del huésped EXTERNO
                        h_ext = sesion.get(Huesped, huesped_ext_id)
                        if h_ext:
                            h_ext.credito_usd = max(0.0, (h_ext.credito_usd or 0.0) - monto_sf)
                        pago["descripcion_extra"] = (
                            f"Saldo aplicado de {nombre_ext} (doc: {doc_ext}) a estadía #{self.id_estadia}"
                        )
                    else:
                        # Descuenta del crédito del TITULAR de esta estadía
                        if estadia_bd and estadia_bd.huespedes:
                            titular = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                            if titular:
                                titular.credito_usd = max(0.0, (titular.credito_usd or 0.0) - monto_sf)

                elif pago["metodo"] in [MetodoPago.CASH_USD, MetodoPago.ZELLE, MetodoPago.DEBIT_CARD]:
                    caja.saldo_principal_usd += pago["monto_usd"]
                else:
                    caja.saldo_principal_bs  += pago["monto_bs"]

            # ── 2. Crear TransaccionCobro ──────────────────────────────────────
            saldo_pendiente_tx = max(0.0, round(pendiente, 2))
            transaccion = TransaccionCobro(
                estadia_id         = self.id_estadia,
                total_seleccionado = self.total_a_pagar,
                total_pagado       = round(total_pagado_usd, 2),
                saldo_pendiente    = saldo_pendiente_tx,
                creado_en          = datetime.now(),
            )
            sesion.add(transaccion)
            sesion.flush()

            # ── 3. Marcar líneas como canceladas ──────────────────────────────
            for linea_id in self.lineas_ids:
                linea = sesion.get(LineaCuenta, linea_id)
                if linea:
                    linea.cancelada      = True
                    linea.transaccion_id = transaccion.id

            # ── 4. Pago parcial → SALDO_PENDIENTE ─────────────────────────────
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
                    concepto       = f"Saldo pendiente de cobro — {resumen}",
                    monto_usd      = saldo_pendiente_tx,
                    cancelada      = False,
                    creado_en      = datetime.now(),
                ))

            # ── 5. Sobrante (pagó de más) ──────────────────────────────────────
            elif pendiente < -0.01:
                monto_sobrante = abs(pendiente)
                ultimo_metodo  = self.pagos_sesion[-1]["metodo"] if self.pagos_sesion else MetodoPago.CASH_USD

                if self.radio_tipo_sobrante and self.radio_tipo_sobrante.value == "credito":
                    # Acreditar SOLO en Huesped.credito_usd — sin tocar deposito_usd
                    if estadia_bd and estadia_bd.huespedes:
                        titular = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                        if titular:
                            titular.credito_usd = (titular.credito_usd or 0.0) + monto_sobrante
                    sesion.add(Pago(
                        estadia_id=self.id_estadia, monto_usd=monto_sobrante,
                        monto_bs=a_bs(monto_sobrante, tasa), es_devolucion=True,
                        metodo=ultimo_metodo, tasa_cambio=tasa,
                        descripcion="Sobrante registrado como saldo a favor (crédito huésped)",
                        creado_en=datetime.now(),
                    ))
                else:
                    c_ppal, c_chica, c_ppal_bs, c_chica_bs = self.campos_desglose_vuelto
                    vp = float(c_ppal.value or 0); vc = float(c_chica.value or 0)
                    vpb = float(c_ppal_bs.value or 0); vcb = float(c_chica_bs.value or 0)

                    if caja.saldo_principal_usd < vp:  raise Exception("Fondos insuficientes — Caja Principal $")
                    if caja.caja_chica_usd      < vc:  raise Exception("Fondos insuficientes — Caja Chica $")
                    if caja.saldo_principal_bs  < vpb: raise Exception("Fondos insuficientes — Caja Principal Bs")
                    if caja.caja_chica_bs       < vcb: raise Exception("Fondos insuficientes — Caja Chica Bs")

                    caja.saldo_principal_usd -= vp
                    caja.caja_chica_usd      -= vc
                    caja.saldo_principal_bs  -= vpb
                    caja.caja_chica_bs       -= vcb

                    sesion.add(Pago(
                        estadia_id=self.id_estadia, monto_usd=monto_sobrante,
                        monto_bs=a_bs(monto_sobrante, tasa), es_devolucion=True,
                        metodo=ultimo_metodo, tasa_cambio=tasa,
                        descripcion=f"Vuelto — P$:{vp:.2f} | C$:{vc:.2f} | PBs:{vpb:.2f} | CBs:{vcb:.2f}",
                        creado_en=datetime.now(),
                    ))

            sesion.commit()
            self.pagina.close(self.dialogo)
            self.pagina.open(ft.SnackBar(
                ft.Text("Cobro registrado correctamente" if saldo_pendiente_tx <= 0.01 else f"Cobro parcial — Quedan ${saldo_pendiente_tx:.2f} pendientes"),
                bgcolor=ft.Colors.GREEN_700 if saldo_pendiente_tx <= 0.01 else ft.Colors.BLUE_700,
            ))
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(ft.Text(f"Error al registrar el pago: {error}"), bgcolor=ft.Colors.RED_700))
        finally:
            sesion.close()

    def mostrar(self):
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)