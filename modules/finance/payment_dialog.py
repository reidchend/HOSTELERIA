# modules/finance/payment_dialog.py
# Compatible con Flet 0.28.3

import flet as ft
from database.connection import SesionLocal
from database.models import (
    Pago,
    Caja,
    MetodoPago,
    Estadia,
    Huesped,
    FolioLinea,
    TipoLinea,
)
from modules.finance.engine import folio as folio_engine
from modules.finance.engine import ledger as led
from sqlalchemy.orm import selectinload
from datetime import datetime
from utils.calculos_financieros import leer_config_financiera, a_bs, a_usd
from modules.finance.gestor_vuelto import GestorVuelto
from modules.finance.bitacora import registrar as _bita
from database.models import TipoEvento as _TE

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN VISUAL POR MÉTODO DE PAGO
# ══════════════════════════════════════════════════════════════════════════════

CONFIGURACION_METODOS = {
    MetodoPago.CASH_USD: {
        "etiqueta": "Efectivo $",
        "icono": ft.Icons.ATTACH_MONEY,
        "color": ft.Colors.GREEN_800,
        "es_bs": False,
    },
    MetodoPago.CASH_BS: {
        "etiqueta": "Efectivo Bs",
        "icono": ft.Icons.MONEY,
        "color": ft.Colors.TEAL_700,
        "es_bs": True,
    },
    MetodoPago.TRANSFER_BS: {
        "etiqueta": "Transferencia",
        "icono": ft.Icons.SWAP_HORIZ,
        "color": ft.Colors.BLUE_700,
        "es_bs": True,
    },
    MetodoPago.PAGO_MOVIL: {
        "etiqueta": "Pago Móvil",
        "icono": ft.Icons.PHONE_ANDROID,
        "color": ft.Colors.PURPLE_700,
        "es_bs": True,
    },
    MetodoPago.ZELLE: {
        "etiqueta": "Zelle",
        "icono": ft.Icons.SEND,
        "color": ft.Colors.INDIGO_700,
        "es_bs": False,
    },
    MetodoPago.DEBIT_CARD: {
        "etiqueta": "T. Débito",
        "icono": ft.Icons.CREDIT_CARD,
        "color": ft.Colors.ORANGE_700,
        "es_bs": True,
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

    def __init__(
        self,
        pagina,
        estadia,
        total_a_pagar,
        al_completar,
        lineas_ids=None,
        checkin_info=None,
        al_cancelar=None,
    ):
        self.pagina = pagina
        self.estadia = estadia
        self.id_estadia = estadia.id
        self.total_a_pagar = total_a_pagar
        self.al_completar = al_completar
        self.lineas_ids = lineas_ids or []
        # Datos del check-in para registrar el mensaje final en bitácora.
        # Si es None, el pago proviene de details.py (no de un check-in nuevo).
        self.checkin_info = checkin_info
        self.al_cancelar = al_cancelar  # Callback cuando se cancela sin pagar
        self.dialogo = None

        sesion = SesionLocal()
        try:
            self.config = leer_config_financiera(sesion)
            self.saldo_favor_disponible = self._leer_credito_titular(sesion)
        finally:
            sesion.close()

        self.pagos_sesion = []
        self.columna_saldo = ft.Column(spacing=6)
        self.columna_pagos_sesion = ft.Column(spacing=6)
        self.area_formulario = ft.Column(spacing=8)
        self.seccion_sobrante = ft.Container(visible=False)
        self.btn_finalizar = None
        self._gestor_vuelto = None
        self._campo_telefono_pm = None
        self._lineas_detalle = self._cargar_lineas_detalle()

    def _on_cancelar(self, _):
        """Maneja el cierre del diálogo de pago. Si es un check-in grupal pendiente, envía el mensaje."""
        ci = self.checkin_info
        if ci and ci.get("es_grupo") and not self.pagos_sesion:
            # No se realizó ningún pago — enviar mensaje de cuenta pendiente
            try:
                from modules.notifications.formatter import checkin_grupal_mensaje
                from modules.notifications import telegram as tg
                from modules.notifications.dispatcher import guardar_telegram_message_id
                from modules.finance.bitacora import registrar as _bita
                from database.models import TipoEvento, BitacoraEvento
                from database.connection import SesionLocal
                
                sesion = SesionLocal()
                bitacora_id = None
                try:
                    evento = _bita(
                        sesion=sesion,
                        pagina=self.pagina,
                        tipo=TipoEvento.CHECKIN,
                        concepto=f"CHECK-IN GRUPO '{ci.get('nombre_grupo', '')}' ${ci.get('monto', 0):.2f} pendiente por cancelar",
                        habitacion=f"Grupo {ci.get('nombre_grupo', '')}",
                        monto_usd=ci.get("monto", 0),
                        confirmado=False,
                        notificar_telegram=False,
                        retornar_evento=True,
                    )
                    if evento:
                        bitacora_id = evento.id
                    sesion.commit()
                except Exception as e:
                    sesion.rollback()
                    print(f"[PaymentDialog] Error bitácora cancelar grupal: {e}")
                finally:
                    sesion.close()
                
                recep = (self.pagina.session.get("usuario_activo") or {}).get("nombre_completo", "")
                msg = checkin_grupal_mensaje(
                    nombre_grupo=ci.get("nombre_grupo", ""),
                    habitaciones=ci.get("habitaciones_data", []),
                    huesped_principal=ci.get("nombre", ""),
                    total_grupo=ci.get("monto", 0),
                    noches=ci.get("noches", 1),
                    fecha_salida=ci.get("fecha_salida", ""),
                    recepcionista=recep,
                    pendiente=True,
                    pagos=[],
                )
                exito, msg_id = tg.enviar_mensaje(msg)
                if exito and msg_id and bitacora_id:
                    guardar_telegram_message_id(bitacora_id, str(msg_id))
            except Exception as e:
                print(f"[PaymentDialog] Error Telegram cancelar grupal: {e}")
        
        self.pagina.close(self.dialogo)
        if self.al_cancelar:
            self.al_cancelar()

    def _cargar_lineas_detalle(self):
        """Carga los detalles de las líneas que se van a cobrar."""
        if not self.lineas_ids:
            return []
        sesion = SesionLocal()
        try:
            lineas = (
                sesion.query(FolioLinea)
                .filter(FolioLinea.id.in_(self.lineas_ids))
                .all()
            )
            return [
                {
                    "concepto": l.concepto or self._nombre_tipo_linea(l.tipo),
                    "monto": float(l.total_usd),
                }
                for l in lineas
            ]
        finally:
            sesion.close()

    def _nombre_tipo_linea(self, tipo):
        """Devuelve el nombre del tipo de línea para mostrar."""
        from database.models import TipoLinea

        nombres = {
            TipoLinea.HOSPEDAJE: "Hospedaje",
            TipoLinea.CARGO_EXTRA: "Cargo extra",
            TipoLinea.SALDO_PENDIENTE: "Saldo pendiente",
        }
        return nombres.get(tipo, str(tipo.value if tipo else "Cobro"))

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
        return round(float(titular.credito_usd or 0), 2) if titular else 0.0

    def _leer_credito_huesped(self, sesion, huesped_id):
        """Devuelve el credito_usd de cualquier huésped por id."""
        h = sesion.get(Huesped, huesped_id)
        return round(float(h.credito_usd or 0), 2) if h else 0.0

    # ══════════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS
    # ══════════════════════════════════════════════════════════════════════════

    def _cargar_lineas(self, sesion):
        if not self.lineas_ids:
            return []
        return sesion.query(FolioLinea).filter(FolioLinea.id.in_(self.lineas_ids)).all()

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
            "estadia": estadia,
            "habitacion": estadia.habitacion,
            "titular": estadia.huespedes[0] if estadia.huespedes else None,
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
            datos = self._datos_para_panel(sesion)
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
                ft.Container(content=self._panel_cobro(), expand=True, padding=18),
            ],
            spacing=0,
            expand=True,
        )

        self.dialogo = ft.AlertDialog(
            title=self._encabezado(datos),
            content=ft.Container(content=cuerpo, width=880, height=540),
            actions=[
                ft.TextButton(
                    "Cancelar", on_click=self._on_cancelar
                ),
                self.btn_finalizar,
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        return self.dialogo

    def _encabezado(self, datos):
        titular = datos["titular"]
        return ft.Row(
            controls=[
                ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE_800, size=22),
                ft.Column(
                    controls=[
                        ft.Text(
                            f"Cobro — Habitación {datos['habitacion'].numero}",
                            weight="bold",
                            size=15,
                        ),
                        ft.Text(
                            titular.nombre_completo if titular else "Huésped",
                            size=11,
                            color=ft.Colors.GREY_600,
                        ),
                    ],
                    spacing=1,
                ),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.CURRENCY_EXCHANGE,
                                size=13,
                                color=ft.Colors.GREY_600,
                            ),
                            ft.Text(
                                f"Tasa: Bs. {self.config.tasa_cambio:,.2f}",
                                size=12,
                                color=ft.Colors.GREY_700,
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
    # PANEL IZQUIERDO — DETALLE DE LÍNEAS
    # ══════════════════════════════════════════════════════════════════════════

    def _panel_factura(self, datos, lineas):
        tasa = self.config.tasa_cambio
        filas_lineas = []

        for linea in lineas:
            if linea.tipo == TipoLinea.HOSPEDAJE:
                icono, color_ico, etiq, color_t = (
                    ft.Icons.BED_OUTLINED,
                    ft.Colors.BLUE_700,
                    "Hospedaje",
                    ft.Colors.BLUE_700,
                )
            elif linea.tipo == TipoLinea.CARGO_EXTRA:
                icono, color_ico, etiq, color_t = (
                    ft.Icons.ROOM_SERVICE,
                    ft.Colors.ORANGE_700,
                    "Servicio (c/IVA)",
                    ft.Colors.ORANGE_700,
                )
            else:
                icono, color_ico, etiq, color_t = (
                    ft.Icons.PENDING_ACTIONS,
                    ft.Colors.RED_700,
                    "Saldo pendiente",
                    ft.Colors.RED_700,
                )

            filas_lineas.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(icono, size=14, color=color_ico),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        linea.concepto, size=11, color=ft.Colors.BLACK87
                                    ),
                                    ft.Container(
                                        content=ft.Text(etiq, size=9, color=color_t),
                                        bgcolor=ft.Colors.with_opacity(0.1, color_t),
                                        padding=ft.padding.symmetric(
                                            horizontal=5, vertical=1
                                        ),
                                        border_radius=4,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        f"${float(linea.total_usd):.2f}",
                                        size=12,
                                        weight="bold",
                                        text_align=ft.TextAlign.RIGHT,
                                    ),
                                    ft.Text(
                                        f"Bs.{a_bs(float(linea.total_usd), tasa):,.0f}",
                                        size=9,
                                        color=ft.Colors.GREY_500,
                                        text_align=ft.TextAlign.RIGHT,
                                    ),
                                ],
                                spacing=1,
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        spacing=8,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    bgcolor=ft.Colors.WHITE,
                    border_radius=7,
                    border=ft.border.all(1, ft.Colors.GREY_100),
                )
            )

        tiene_hosp = any(l.tipo == TipoLinea.HOSPEDAJE for l in lineas)
        tiene_extras = any(l.tipo == TipoLinea.CARGO_EXTRA for l in lineas)
        nota_iva = []
        if tiene_hosp:
            nota_iva.append("🏨 Hospedaje: precio sin IVA")
        if tiene_extras:
            nota_iva.append("🍽 Servicios: precio con IVA incluido")

        self.columna_saldo.controls = self._filas_saldo()

        return ft.Column(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "CONCEPTOS A COBRAR",
                            size=9,
                            weight="bold",
                            color=ft.Colors.BLUE_GREY_400,
                        ),
                        ft.Column(controls=filas_lineas, spacing=5),
                        ft.Divider(height=1, color=ft.Colors.GREY_200),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    n, size=9, color=ft.Colors.GREY_500, italic=True
                                )
                                for n in nota_iva
                            ],
                            spacing=2,
                        )
                        if nota_iva
                        else ft.Container(),
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Text(
                                        "TOTAL A COBRAR:",
                                        size=13,
                                        weight="bold",
                                        expand=True,
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text(
                                                f"${self.total_a_pagar:.2f}",
                                                size=18,
                                                weight="bold",
                                                color=ft.Colors.BLUE_900,
                                            ),
                                            ft.Text(
                                                f"Bs. {a_bs(self.total_a_pagar, tasa):,.2f}",
                                                size=10,
                                                color=ft.Colors.GREY_600,
                                                text_align=ft.TextAlign.RIGHT,
                                            ),
                                        ],
                                        spacing=1,
                                        horizontal_alignment=ft.CrossAxisAlignment.END,
                                    ),
                                ]
                            ),
                            bgcolor=ft.Colors.BLUE_50,
                            padding=10,
                            border_radius=8,
                        ),
                        ft.Divider(height=1, color=ft.Colors.GREY_200),
                        self.columna_saldo,
                    ],
                    spacing=8,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
        )

    def _filas_saldo(self):
        pendiente = self._pendiente()
        abonado = sum(p["monto_usd"] for p in self.pagos_sesion)
        tasa = self.config.tasa_cambio
        filas = []

        if self.pagos_sesion:
            filas.append(
                ft.Row(
                    controls=[
                        ft.Text(
                            "Abonado ahora:",
                            size=11,
                            expand=True,
                            color=ft.Colors.GREEN_700,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    f"${abonado:.2f}",
                                    size=12,
                                    weight="bold",
                                    color=ft.Colors.GREEN_700,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                                ft.Text(
                                    f"Bs. {a_bs(abonado, tasa):,.2f}",
                                    size=10,
                                    color=ft.Colors.GREEN_600,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ],
                            spacing=1,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                        ),
                    ]
                )
            )

        if pendiente > 0.01:
            filas.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.PENDING,
                                        color=ft.Colors.RED_700,
                                        size=15,
                                    ),
                                    ft.Text(
                                        "PENDIENTE:",
                                        size=12,
                                        weight="bold",
                                        color=ft.Colors.RED_700,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        f"${pendiente:.2f}",
                                        size=15,
                                        weight="bold",
                                        color=ft.Colors.RED_700,
                                    ),
                                ]
                            ),
                            ft.Text(
                                f"Bs. {a_bs(pendiente, tasa):,.2f}",
                                size=11,
                                color=ft.Colors.RED_400,
                                text_align=ft.TextAlign.RIGHT,
                            ),
                            ft.Text(
                                "⚠ La diferencia quedará como saldo pendiente.",
                                size=9,
                                color=ft.Colors.RED_400,
                                italic=True,
                            )
                            if self.pagos_sesion
                            else ft.Container(),
                        ],
                        spacing=3,
                    ),
                    bgcolor=ft.Colors.RED_50,
                    padding=10,
                    border_radius=8,
                )
            )
        elif pendiente < -0.01:
            sobrante = abs(pendiente)
            filas.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.ARROW_CIRCLE_UP,
                                        color=ft.Colors.ORANGE_700,
                                        size=15,
                                    ),
                                    ft.Text(
                                        "SOBRANTE:",
                                        size=12,
                                        weight="bold",
                                        color=ft.Colors.ORANGE_700,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        f"${sobrante:.2f}",
                                        size=15,
                                        weight="bold",
                                        color=ft.Colors.ORANGE_700,
                                    ),
                                ]
                            ),
                            ft.Text(
                                f"Bs. {a_bs(sobrante, tasa):,.2f}",
                                size=11,
                                color=ft.Colors.ORANGE_400,
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
            filas.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE,
                                color=ft.Colors.GREEN_700,
                                size=16,
                            ),
                            ft.Text(
                                "CUENTA SALDADA",
                                size=12,
                                weight="bold",
                                color=ft.Colors.GREEN_700,
                            ),
                        ],
                        spacing=6,
                    ),
                    bgcolor=ft.Colors.GREEN_50,
                    padding=10,
                    border_radius=8,
                )
            )
        return filas

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL DERECHO
    # ══════════════════════════════════════════════════════════════════════════

    def _panel_cobro(self):
        self.area_formulario.controls = [
            ft.Container(
                content=ft.Text(
                    "← Selecciona un método para ingresar el pago",
                    size=12,
                    color=ft.Colors.GREY_500,
                    italic=True,
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
                color=ft.Colors.TEAL_700, side=ft.BorderSide(1.2, ft.Colors.TEAL_300)
            ),
            height=38,
            on_click=lambda _: self._abrir_buscador_huesped_externo(),
        )

        return ft.Column(
            controls=[
                ft.Text(
                    "MÉTODO DE PAGO",
                    size=9,
                    weight="bold",
                    color=ft.Colors.BLUE_GREY_400,
                ),
                ft.Row(controls=botones, wrap=True, spacing=8, run_spacing=8),
                ft.Row(
                    controls=[btn_saldo_favor, btn_saldo_externo], spacing=8, wrap=True
                ),
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                self.area_formulario,
                ft.Divider(height=1, color=ft.Colors.GREY_200),
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.RECEIPT, size=13, color=ft.Colors.BLUE_GREY_300
                        ),
                        ft.Text(
                            "PAGOS DE ESTA SESIÓN",
                            size=9,
                            weight="bold",
                            color=ft.Colors.BLUE_GREY_300,
                        ),
                    ],
                    spacing=5,
                ),
                self.columna_pagos_sesion,
                self.seccion_sobrante,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # SELECCIÓN DE MÉTODO
    # ══════════════════════════════════════════════════════════════════════════

    def seleccionar_metodo(self, metodo):
        cfg = CONFIGURACION_METODOS[metodo]
        es_bs = cfg["es_bs"]
        necesita_referencia = metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS]
        es_pago_movil = metodo == MetodoPago.PAGO_MOVIL
        tasa = self.config.tasa_cambio

        pendiente = self._pendiente()
        valor_sug = (
            f"{a_bs(pendiente, tasa):.2f}"
            if (pendiente > 0 and es_bs)
            else (f"{pendiente:.2f}" if pendiente > 0 else "0.00")
        )

        campo_monto = ft.TextField(
            label=f"Monto recibido ({'Bs.' if es_bs else 'USD'})",
            value=valor_sug,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
            autofocus=True,
            expand=True,
        )
        campo_ref = ft.TextField(
            label="Nro. Referencia / Confirmación",
            visible=necesita_referencia,
            expand=True,
        )
        # Campo teléfono — solo para Pago Móvil
        campo_telefono = ft.TextField(
            label="Teléfono (Pago Móvil)",
            hint_text="04XX-XXX-XXXX",
            visible=es_pago_movil,
            expand=True,
        )
        # Guardar referencia para recuperarlo al finalizar
        if es_pago_movil:
            self._campo_telefono_pm = campo_telefono

        def agregar(evento):
            try:
                valor = float(campo_monto.value.replace(",", ".") or 0)
                if valor <= 0:
                    campo_monto.error_text = "Ingrese un monto válido"
                    campo_monto.update()
                    return
                campo_monto.error_text = None
                monto_usd = a_usd(valor, tasa) if es_bs else valor
                monto_bs = valor if es_bs else a_bs(valor, tasa)

                pago_dict = {
                    "metodo": metodo,
                    "monto_usd": monto_usd,
                    "monto_bs": monto_bs,
                    "referencia": campo_ref.value.strip()
                    if necesita_referencia
                    else "",
                    "etiqueta": cfg["etiqueta"],
                    "color": cfg["color"],
                    "icono": cfg["icono"],
                    "visualizacion": f"Bs. {valor:,.2f}" if es_bs else f"${valor:.2f}",
                }
                # Guardar teléfono dentro del dict si es Pago Móvil
                if es_pago_movil:
                    pago_dict["telefono_pm"] = campo_telefono.value.strip()

                self.pagos_sesion.append(pago_dict)
                self.refrescar_interfaz()
            except (ValueError, AttributeError):
                campo_monto.error_text = "Número inválido"
                campo_monto.update()

        # Construir fila de campos según método
        if es_pago_movil:
            fila_campos = ft.Column(
                [
                    ft.Row([campo_monto, campo_ref], spacing=10),
                    campo_telefono,
                ],
                spacing=8,
            )
        elif necesita_referencia:
            fila_campos = ft.Row([campo_monto, campo_ref], spacing=10)
        else:
            fila_campos = ft.Row([campo_monto], spacing=10)

        self.area_formulario.controls = [
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(cfg["icono"], color=cfg["color"], size=18),
                                ft.Text(
                                    cfg["etiqueta"],
                                    weight="bold",
                                    color=cfg["color"],
                                    size=13,
                                ),
                            ],
                            spacing=6,
                        ),
                        fila_campos,
                        ft.ElevatedButton(
                            "+ AGREGAR PAGO",
                            bgcolor=cfg["color"],
                            color=ft.Colors.WHITE,
                            on_click=agregar,
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
        self.pagina.update()

    def refrescar_interfaz(self):
        self.columna_saldo.controls = self._filas_saldo()
        self.columna_pagos_sesion.controls = [
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(p["icono"], size=14, color=p["color"]),
                        ft.Text(p["etiqueta"], size=12, expand=True),
                        ft.Text(p["visualizacion"], size=12, weight="bold"),
                        ft.Text(
                            f"  (${p['monto_usd']:.2f})",
                            size=10,
                            color=ft.Colors.GREY_600,
                        ),
                        ft.IconButton(
                            ft.Icons.REMOVE_CIRCLE_OUTLINE,
                            icon_size=15,
                            icon_color=ft.Colors.RED_400,
                            tooltip="Quitar este pago",
                            on_click=lambda _, i=idx: self.quitar_pago(i),
                        ),
                    ],
                    spacing=4,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                bgcolor=ft.Colors.with_opacity(0.06, p["color"]),
                border_radius=7,
            )
            for idx, p in enumerate(self.pagos_sesion)
        ]
        pendiente = self._pendiente()
        if pendiente < -0.01:
            self._activar_gestor_vuelto(abs(pendiente))
            self.btn_finalizar.disabled = False
            self.btn_finalizar.bgcolor = ft.Colors.ORANGE_700
            self.btn_finalizar.text = "CONFIRMAR Y GESTIONAR SOBRANTE"
        elif self.pagos_sesion:
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled = False
            self.btn_finalizar.bgcolor = (
                ft.Colors.GREEN_700 if abs(pendiente) <= 0.01 else ft.Colors.BLUE_700
            )
            self.btn_finalizar.text = (
                "FINALIZAR COBRO"
                if abs(pendiente) <= 0.01
                else f"COBRAR PARCIAL (quedan ${pendiente:.2f})"
            )
        else:
            self.seccion_sobrante.visible = False
            self.btn_finalizar.disabled = True
            self.btn_finalizar.bgcolor = ft.Colors.GREY_400
            self.btn_finalizar.text = "FINALIZAR COBRO"
        self.pagina.update()

    def quitar_pago(self, indice):
        self.pagos_sesion.pop(indice)
        self.refrescar_interfaz()

    # ══════════════════════════════════════════════════════════════════════════
    # SALDO A FAVOR PROPIO  —  fuente: Huesped.credito_usd del titular
    # ══════════════════════════════════════════════════════════════════════════

    def _aplicar_saldo_favor(self):
        pendiente = self._pendiente()
        disponible = self.saldo_favor_disponible
        if disponible <= 0.01 or pendiente <= 0.01:
            return
        monto_aplicar = round(min(disponible, pendiente), 2)
        tasa = self.config.tasa_cambio
        self.pagos_sesion.append(
            {
                "metodo": MetodoPago.SALDO_FAVOR,
                "monto_usd": monto_aplicar,
                "monto_bs": a_bs(monto_aplicar, tasa),
                "referencia": "",
                "etiqueta": f"Saldo a Favor del titular (${monto_aplicar:.2f})",
                "color": ft.Colors.GREEN_800,
                "icono": ft.Icons.ACCOUNT_BALANCE_WALLET,
                "visualizacion": f"${monto_aplicar:.2f}",
                "es_saldo_favor": True,
                # Sin huesped_externo_id  →  descuenta del titular de esta estadía
            }
        )
        self.saldo_favor_disponible = round(disponible - monto_aplicar, 2)
        self.refrescar_interfaz()

    # ══════════════════════════════════════════════════════════════════════════
    # BUSCADOR DE SALDO EXTERNO  —  lista + búsqueda
    # ══════════════════════════════════════════════════════════════════════════

    def _abrir_buscador_huesped_externo(self):
        """
        Diálogo de saldo externo con navegación interna entre vistas.

        REGLA FLET 0.28.3: page.close() solo se llama desde un on_click
        de botón explícito del usuario. Nunca desde código programático,
        porque la pila de diálogos no distingue por referencia y puede
        cerrar el diálogo de pagos principal.

        Flujo:
          Vista 1 → lista de huéspedes con saldo (+ buscador)
          Vista 2 → confirmar monto del huésped seleccionado
          Vista 3 → éxito: el pago ya está en la lista, solo cerrar
        """
        contenedor = ft.Column(spacing=10, tight=True)
        titulo_txt = ft.Text("Saldo de otro huésped", weight="bold")

        dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.PERSON_SEARCH, color=ft.Colors.TEAL_700),
                    titulo_txt,
                ],
                spacing=8,
            ),
            content=ft.Container(content=contenedor, width=460),
            actions=[],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        def _set_vista(controls, actions, titulo):
            """Reemplaza contenido y acciones del diálogo sin cerrarlo."""
            titulo_txt.value = titulo
            contenedor.controls = controls
            dlg.actions = actions
            if dlg.page:
                dlg.update()

        # ══════════════════════════════════════════════════════════════════════
        # VISTA 1 — lista de huéspedes
        # ══════════════════════════════════════════════════════════════════════
        lista_col = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO)
        campo_busqueda = ft.TextField(
            label="Filtrar por documento o nombre",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
        )

        def _cargar(termino=""):
            sesion = SesionLocal()
            try:
                q = sesion.query(Huesped).filter(Huesped.credito_usd > 0)
                if termino:
                    q = q.filter(
                        (Huesped.documento.ilike(f"%{termino}%"))
                        | (Huesped.nombre.ilike(f"%{termino}%"))
                        | (Huesped.apellido.ilike(f"%{termino}%"))
                    )
                huespedes = q.order_by(Huesped.credito_usd.desc()).limit(30).all()
                lista_col.controls = (
                    [_fila_huesped(h, float(h.credito_usd or 0)) for h in huespedes]
                    if huespedes
                    else [
                        ft.Text(
                            "Sin huéspedes con saldo a favor.",
                            size=12,
                            color=ft.Colors.GREY_400,
                            italic=True,
                        )
                    ]
                )
            finally:
                sesion.close()
            if lista_col.page:
                lista_col.update()

        def _fila_huesped(h, credito):
            hid = h.id
            doc = h.documento
            nombre = h.nombre_completo

            def _ir_vista2(_):
                mostrar_vista2(hid, doc, nombre, credito)

            return ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(nombre, size=12, weight="bold"),
                                ft.Text(
                                    f"Doc: {doc}", size=10, color=ft.Colors.GREY_600
                                ),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(
                                f"${credito:.2f}",
                                size=13,
                                weight="bold",
                                color=ft.Colors.WHITE,
                            ),
                            bgcolor=ft.Colors.GREEN_700,
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                            border_radius=8,
                        ),
                        ft.ElevatedButton(
                            "Usar",
                            style=ft.ButtonStyle(
                                color=ft.Colors.TEAL_700,
                                bgcolor=ft.Colors.with_opacity(
                                    0.08, ft.Colors.TEAL_700
                                ),
                                side=ft.BorderSide(1, ft.Colors.TEAL_300),
                                shape=ft.RoundedRectangleBorder(radius=6),
                            ),
                            height=32,
                            on_click=_ir_vista2,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                bgcolor=ft.Colors.WHITE,
                border_radius=8,
                border=ft.border.all(1, ft.Colors.GREY_100),
            )

        def mostrar_vista1():
            campo_busqueda.on_change = lambda ev: _cargar(campo_busqueda.value.strip())
            _set_vista(
                controls=[
                    campo_busqueda,
                    ft.Container(
                        content=lista_col,
                        height=260,
                        border=ft.border.all(1, ft.Colors.GREY_200),
                        border_radius=8,
                        padding=8,
                    ),
                ],
                actions=[
                    ft.TextButton(
                        "Cancelar",
                        on_click=lambda _: self.pagina.close(dlg),
                    ),
                ],
                titulo="Saldo de otro huésped",
            )

        # ══════════════════════════════════════════════════════════════════════
        # VISTA 2 — confirmar monto
        # ══════════════════════════════════════════════════════════════════════
        def mostrar_vista2(hid, doc, nombre, credito):
            pendiente = self._pendiente()
            monto_sug = round(min(credito, max(pendiente, 0.0)), 2)
            campo_monto = ft.TextField(
                label="Monto a aplicar",
                value=f"{monto_sug:.2f}",
                suffix_text="USD",
                keyboard_type=ft.KeyboardType.NUMBER,
                text_align=ft.TextAlign.RIGHT,
                width=200,
            )
            error_txt = ft.Text("", color=ft.Colors.RED_700, size=11)

            def _aplicar(_):
                # Parsear el valor limpiando cualquier símbolo residual
                try:
                    limpio = (
                        (campo_monto.value or "")
                        .replace("$", "")
                        .replace(",", ".")
                        .strip()
                    )
                    monto = round(float(limpio), 2)
                except (ValueError, AttributeError):
                    error_txt.value = "Número inválido"
                    error_txt.update()
                    return

                if monto <= 0:
                    error_txt.value = "El monto debe ser mayor a 0"
                    error_txt.update()
                    return
                if monto > credito + 0.01:
                    error_txt.value = f"Máximo disponible: ${credito:.2f}"
                    error_txt.update()
                    return

                tasa = self.config.tasa_cambio
                self.pagos_sesion.append(
                    {
                        "metodo": MetodoPago.SALDO_FAVOR,
                        "monto_usd": monto,
                        "monto_bs": a_bs(monto, tasa),
                        "referencia": "",
                        "etiqueta": f"Saldo de {nombre} (${monto:.2f})",
                        "color": ft.Colors.TEAL_700,
                        "icono": ft.Icons.PERSON_PIN,
                        "visualizacion": f"${monto:.2f}",
                        "es_saldo_favor": True,
                        "huesped_externo_id": hid,
                        "huesped_externo_nombre": nombre,
                        "huesped_externo_doc": doc,
                    }
                )

                # Actualizar el panel de pagos ANTES de tocar este diálogo
                self.refrescar_interfaz()

                # Mostrar vista de éxito — el usuario cierra manualmente.
                # NO se llama page.close() aquí para no cerrar el modal de pagos.
                mostrar_vista3(nombre, monto)

            _set_vista(
                controls=[
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.PERSON,
                                            color=ft.Colors.TEAL_700,
                                            size=16,
                                        ),
                                        ft.Text(nombre, size=13, weight="bold"),
                                    ],
                                    spacing=6,
                                ),
                                ft.Text(
                                    f"Documento: {doc}",
                                    size=11,
                                    color=ft.Colors.GREY_600,
                                ),
                                ft.Text(
                                    f"Crédito disponible: ${credito:.2f}",
                                    size=12,
                                    color=ft.Colors.GREEN_700,
                                    weight="bold",
                                ),
                                ft.Divider(height=6),
                                campo_monto,
                                error_txt,
                            ],
                            spacing=8,
                        ),
                        bgcolor=ft.Colors.TEAL_50,
                        padding=14,
                        border_radius=10,
                        border=ft.border.all(1, ft.Colors.TEAL_100),
                    ),
                ],
                actions=[
                    ft.TextButton(
                        "← Volver", on_click=lambda _: (mostrar_vista1(), _cargar())
                    ),
                    ft.ElevatedButton(
                        "Aplicar saldo",
                        icon=ft.Icons.CHECK,
                        bgcolor=ft.Colors.TEAL_700,
                        color=ft.Colors.WHITE,
                        on_click=_aplicar,
                    ),
                ],
                titulo=f"Confirmar — {nombre}",
            )

        # ══════════════════════════════════════════════════════════════════════
        # VISTA 3 — éxito: pago ya registrado en la lista
        # ══════════════════════════════════════════════════════════════════════
        def mostrar_vista3(nombre, monto):
            pendiente_restante = self._pendiente()
            if pendiente_restante > 0.01:
                msg = f"Quedan ${pendiente_restante:.2f} por cobrar. Puedes agregar otro metodo de pago."
                color_msg = ft.Colors.BLUE_700
            else:
                msg = "La cuenta ha quedado saldada."
                color_msg = ft.Colors.GREEN_700

            _set_vista(
                controls=[
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.CHECK_CIRCLE,
                                            color=ft.Colors.GREEN_700,
                                            size=28,
                                        ),
                                        ft.Text(
                                            "Saldo aplicado",
                                            size=16,
                                            weight="bold",
                                            color=ft.Colors.GREEN_700,
                                        ),
                                    ],
                                    spacing=10,
                                ),
                                ft.Text(
                                    f"Se aplicaron ${monto:.2f} del crédito de {nombre}.",
                                    size=12,
                                ),
                                ft.Text(msg, size=12, color=color_msg),
                            ],
                            spacing=10,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        bgcolor=ft.Colors.GREEN_50,
                        padding=20,
                        border_radius=10,
                        border=ft.border.all(1, ft.Colors.GREEN_200),
                        alignment=ft.alignment.center,
                    ),
                ],
                actions=[
                    ft.ElevatedButton(
                        "Cerrar y continuar",
                        icon=ft.Icons.ARROW_BACK,
                        bgcolor=ft.Colors.BLUE_700,
                        color=ft.Colors.WHITE,
                        on_click=lambda _: self.pagina.close(dlg),
                    ),
                ],
                titulo="Saldo aplicado correctamente",
            )

        # Carga inicial y abrir
        _cargar()
        mostrar_vista1()
        self.pagina.open(dlg)

    def _activar_gestor_vuelto(self, sobrante_usd):
        """
        Crea/actualiza el GestorVuelto inline y lo muestra en seccion_sobrante.
        Se llama cada vez que el sobrante cambia en refrescar_interfaz.
        
        Opciones:
        - credito: dejar como saldo a favor del huésped
        - no_devolver: el cliente dice "quédese con el cambio", no se entrega nada
        - vuelto: entregar vuelto físicamente
        """
        tasa = self.config.tasa_cambio

        # Recrear solo si el monto cambió para no perder lo que el usuario ingresó
        if (
            self._gestor_vuelto is None
            or abs(self._gestor_vuelto.monto_usd - sobrante_usd) > 0.01
        ):
            self._gestor_vuelto = GestorVuelto(
                monto_usd=sobrante_usd,
                tasa=tasa,
                pagina=self.pagina,
            )

        # Opción de crédito vs.no devolver vs vuelto físico
        sobrante_bs = a_bs(sobrante_usd, tasa)
        radio = ft.RadioGroup(
            content=ft.Column(
                controls=[
                    ft.Radio(
                        value="credito",
                        label=f"Dejar ${sobrante_usd:.2f} como saldo a favor  (Bs. {sobrante_bs:,.2f})",
                    ),
                    ft.Radio(
                        value="no_devolver",
                        label=f"💰 Dejar como propina — No se entrega nada",
                    ),
                    ft.Radio(value="vuelto", label="Entregar vuelto ahora"),
                ]
            ),
            value=getattr(self, "_radio_sobrante_valor", "no_devolver"),
        )
        self._radio_sobrante = radio
        panel_gestor = ft.Column(
            controls=[self._gestor_vuelto.construir()],
            visible=(radio.value == "vuelto"),
        )

        def cambiar_modo(_):
            self._radio_sobrante_valor = radio.value
            panel_gestor.visible = radio.value == "vuelto"
            self.pagina.update()

        radio.on_change = cambiar_modo

        self.seccion_sobrante.visible = True
        self.seccion_sobrante.content = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.INFO_OUTLINE,
                                color=ft.Colors.ORANGE_700,
                                size=16,
                            ),
                            ft.Text(
                                f"Sobrante: ${sobrante_usd:.2f}  ·  Bs. {sobrante_bs:,.2f}",
                                weight="bold",
                                color=ft.Colors.ORANGE_700,
                                size=13,
                            ),
                        ],
                        spacing=6,
                    ),
                    radio,
                    panel_gestor,
                ],
                spacing=10,
            ),
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

            tasa = self.config.tasa_cambio
            total_pagado_usd = sum(p["monto_usd"] for p in self.pagos_sesion)
            pendiente = self._pendiente()

            estadia_bd = (
                sesion.query(Estadia)
                .options(selectinload(Estadia.huespedes))
                .filter(Estadia.id == self.id_estadia)
                .first()
            )

            from decimal import Decimal as _D2

            # ── 1. Registrar cada Pago + asiento PAGO en el ledger ────────────
            for pago in self.pagos_sesion:
                nuevo_pago = Pago(
                    estadia_id=self.id_estadia,
                    monto_usd=pago["monto_usd"],
                    monto_bs=pago["monto_bs"],
                    tasa_cambio=tasa,
                    metodo=pago["metodo"],
                    referencia=pago.get("referencia") or "—",
                    descripcion=pago.get("descripcion_extra", "Cobro de factura"),
                    creado_en=datetime.now(),
                    es_devolucion=False,
                )
                sesion.add(nuevo_pago)
                sesion.flush()

                # Actualizar caja y crédito según método
                if pago.get("es_saldo_favor"):
                    monto_sf = pago["monto_usd"]
                    huesped_ext_id = pago.get("huesped_externo_id")
                    doc_ext = pago.get("huesped_externo_doc", "—")
                    nombre_ext = pago.get("huesped_externo_nombre", "")
                    if huesped_ext_id:
                        h_ext = sesion.get(Huesped, huesped_ext_id)
                        if h_ext:
                            h_ext.credito_usd = max(
                                _D2("0"),
                                (_D2(str(h_ext.credito_usd or 0)) - _D2(str(monto_sf))),
                            )
                        nuevo_pago.descripcion = f"Saldo aplicado de {nombre_ext} (doc: {doc_ext}) a estadía #{self.id_estadia}"
                    else:
                        if estadia_bd and estadia_bd.huespedes:
                            titular = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                            if titular:
                                titular.credito_usd = max(
                                    _D2("0"),
                                    (
                                        _D2(str(titular.credito_usd or 0))
                                        - _D2(str(monto_sf))
                                    ),
                                )
                elif pago["metodo"] in [
                    MetodoPago.CASH_USD,
                    MetodoPago.ZELLE,
                ]:
                    caja.saldo_principal_usd = _D2(
                        str(caja.saldo_principal_usd or 0)
                    ) + _D2(str(pago["monto_usd"]))
                elif pago["metodo"] == MetodoPago.DEBIT_CARD:
                    # Tarjeta Débito: entra en BS a nuestro banco
                    caja.saldo_principal_bs = _D2(
                        str(caja.saldo_principal_bs or 0)
                    ) + _D2(str(pago["monto_bs"]))
                    caja.saldo_principal_bs = _D2(
                        str(caja.saldo_principal_bs or 0)
                    ) + _D2(str(pago["monto_bs"]))

                # Asiento contable PAGO
                led.registrar_pago(
                    sesion,
                    estadia_id=self.id_estadia,
                    concepto=nuevo_pago.descripcion or "Pago",
                    monto_usd=_D2(str(pago["monto_usd"])),
                    tasa=_D2(str(tasa)),
                    referencia=pago.get("referencia") or "—",
                    pago_id=nuevo_pago.id,
                )

            # ── 2. Marcar líneas del folio como canceladas ────────────────────
            folio_engine.cancelar_lineas(sesion, self.lineas_ids)
            saldo_pendiente_tx = round(pendiente, 2)

            # ── 3. Pago parcial → nueva FolioLinea + CARGO en ledger ──────────
            if saldo_pendiente_tx > 0.01:
                conceptos = [
                    sesion.get(FolioLinea, lid).concepto
                    for lid in self.lineas_ids
                    if sesion.get(FolioLinea, lid)
                ]
                resumen = "; ".join(conceptos[:3])
                if len(conceptos) > 3:
                    resumen += f" (+{len(conceptos) - 3} más)"
                folio_engine.crear_saldo_pendiente(
                    sesion,
                    estadia_id=self.id_estadia,
                    monto_usd=_D2(str(saldo_pendiente_tx)),
                    concepto=f"Saldo pendiente — {resumen}",
                    config=self.config,
                )

            # ── 4. Sobrante (pagó de más) ─────────────────────────────────────
            elif pendiente < -0.01:
                monto_sobrante = abs(pendiente)

                modo_sobrante = getattr(self, "_radio_sobrante_valor", "no_devolver")
                
                if modo_sobrante == "no_devolver":
                    # El cliente deja el excedente como propina - no se entrega nada
                    # El sobrante queda en la caja del hotel (ya registrado en caja)
                    pago_sob = Pago(
                        estadia_id=self.id_estadia,
                        monto_usd=monto_sobrante,
                        monto_bs=a_bs(monto_sobrante, tasa),
                        es_devolucion=False,  # No es devolución, es propina
                        metodo=MetodoPago.CASH_BS,
                        tasa_cambio=tasa,
                        descripcion="Propina del cliente",
                        creado_en=datetime.now(),
                    )
                    sesion.add(pago_sob)
                    sesion.flush()
                    led.registrar_pago(
                        sesion,
                        estadia_id=self.id_estadia,
                        concepto="Propina del cliente",
                        monto_usd=_D2(str(monto_sobrante)),
                        tasa=_D2(str(tasa)),
                        referencia="—",
                        pago_id=pago_sob.id,
                    )
                elif modo_sobrante == "credito":
                    if estadia_bd and estadia_bd.huespedes:
                        titular = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                        if titular:
                            titular.credito_usd = _D2(
                                str(titular.credito_usd or 0)
                            ) + _D2(str(monto_sobrante))
                            titular.credito_origen = "saldo"
                    pago_sob = Pago(
                        estadia_id=self.id_estadia,
                        monto_usd=monto_sobrante,
                        monto_bs=a_bs(monto_sobrante, tasa),
                        es_devolucion=True,
                        metodo=MetodoPago.CASH_USD,
                        tasa_cambio=tasa,
                        descripcion="Sobrante → saldo a favor del huésped",
                        creado_en=datetime.now(),
                    )
                    sesion.add(pago_sob)
                    sesion.flush()
                    led.registrar_devolucion(
                        sesion,
                        estadia_id=self.id_estadia,
                        concepto="Sobrante → saldo a favor del huésped",
                        monto_usd=_D2(str(monto_sobrante)),
                        tasa=_D2(str(tasa)),
                        pago_id=pago_sob.id,
                    )
                else:
                    if (
                        self._gestor_vuelto is None
                        or not self._gestor_vuelto.es_valido()
                    ):
                        raise Exception(
                            "El monto a entregar excede el vuelto disponible. "
                            "Reduce los montos."
                        )
                    # Obtener titular para acreditar el remanente
                    titular_id = None
                    if estadia_bd and estadia_bd.huespedes:
                        titular_id = estadia_bd.huespedes[0].id
                    self._gestor_vuelto.aplicar(
                        sesion,
                        estadia_id=self.id_estadia,
                        titular_id=titular_id,
                    )

            # ── Registrar bitácora + Telegram ────────────────────────────────────

            hab_num = ""
            if estadia_bd and estadia_bd.habitacion:
                hab_num = estadia_bd.habitacion.numero

            if self.checkin_info:
                ci = self.checkin_info
                es_pendiente = saldo_pendiente_tx > 0.01
                bitacora_event_id = ci.get("bitacora_event_id")

                reply_to_msg_id = None
                if bitacora_event_id:
                    try:
                        from modules.notifications.dispatcher import (
                            obtener_telegram_message_id,
                        )

                        reply_to_msg_id = obtener_telegram_message_id(bitacora_event_id)
                        if reply_to_msg_id:
                            reply_to_msg_id = int(reply_to_msg_id)
                    except Exception as e:
                        print(f"[PaymentDialog] Error al obtener reply_to: {e}")

                _bita(
                    sesion=sesion,
                    pagina=self.pagina,
                    tipo=_TE.CHECKIN,
                    habitacion=hab_num,
                    concepto=(
                        f"Hab{ci['habitacion']} ${ci['monto']:.2f} "
                        + (
                            "pendiente por cancelar"
                            if es_pendiente
                            else f"cancelado — {ci['nombre']}"
                        )
                    ),
                    monto_usd=total_pagado_usd,
                    monto_bs=sum(p.get("monto_bs", 0) for p in self.pagos_sesion),
                    confirmado=not es_pendiente,
                    notificar_telegram=False,
                )

                try:
                    from modules.notifications.formatter import pago_respuesta, checkin_grupal_mensaje
                    from modules.notifications.dispatcher import enviar_texto

                    recep = (self.pagina.session.get("usuario_activo") or {}).get(
                        "nombre_completo", ""
                    )
                    
                    # Si es un check-in grupal, usar el formato grupal
                    if ci.get("es_grupo"):
                        habitaciones_data = ci.get("habitaciones_data", [])
                        nombre_grupo = ci.get("nombre_grupo", ci.get("habitacion", "Grupo"))
                        
                        msg = checkin_grupal_mensaje(
                            nombre_grupo=nombre_grupo,
                            habitaciones=habitaciones_data,
                            huesped_principal=ci.get("nombre", ""),
                            total_grupo=ci.get("monto", total_pagado_usd),
                            noches=ci.get("noches", 1),
                            fecha_salida=ci.get("fecha_salida", ""),
                            recepcionista=recep,
                            pagos=self.pagos_sesion,
                            pendiente=False,
                        )
                    else:
                        # Si hay sobrante y se seleccionó "propina", no mostrar pendiente
                        modo_sobrante = getattr(self, "_radio_sobrante_valor", None)
                        saldo_a_mostrar = saldo_pendiente_tx
                        if pendiente < -0.01 and modo_sobrante == "no_devolver":
                            saldo_a_mostrar = 0  # La propina ya se quedó en caja
                        
                        msg = pago_respuesta(
                            habitacion=ci["habitacion"],
                            nombre=ci["nombre"],
                            monto_pagado=total_pagado_usd,
                            pagos=self.pagos_sesion,
                            saldo_pendiente=saldo_a_mostrar,
                            recepcionista=recep,
                            es_respuesta=reply_to_msg_id is not None,
                            lineas_detalle=self._lineas_detalle,
                            precio_habitacion=ci.get("monto", total_pagado_usd),
                            es_operativo=ci.get("es_operativo", False),
                            fecha_salida=ci.get("fecha_salida", ""),
                        )
                    enviar_texto(
                        msg,
                        reply_to_message_id=reply_to_msg_id,
                    )
                except Exception as _e:
                    print(f"[PaymentDialog] Error Telegram checkin: {_e}")

            else:
                # Pago desde details.py (no es check-in nuevo) → bitácora normal + Telegram
                _bita(
                    sesion=sesion,
                    pagina=self.pagina,
                    tipo=_TE.PAGO,
                    habitacion=hab_num,
                    concepto=(
                        f"Cuenta pendiente de ${self.total_a_pagar:.2f} — "
                        f"{'Completo' if saldo_pendiente_tx <= 0.01 else f'Parcial, quedan ${saldo_pendiente_tx:.2f}'}"
                    ),
                    monto_usd=total_pagado_usd,
                    monto_bs=sum(p.get("monto_bs", 0) for p in self.pagos_sesion),
                    metodo_pago=", ".join(
                        {p["metodo"].value for p in self.pagos_sesion}
                    ),
                    confirmado=saldo_pendiente_tx <= 0.01,
                )

                # Telegram — mensaje de pago a cuenta existente
                try:
                    from modules.notifications.formatter import pago_cuenta
                    from modules.notifications.dispatcher import enviar_texto

                    recep = (self.pagina.session.get("usuario_activo") or {}).get(
                        "nombre_completo", ""
                    )
                    nombre_huesped = ""
                    if estadia_bd and estadia_bd.huespedes:
                        titular = sesion.get(Huesped, estadia_bd.huespedes[0].id)
                        if titular:
                            nombre_huesped = titular.nombre_completo

                    es_abono = saldo_pendiente_tx > 0.01

                    cargos_extras = [
                        l for l in self._lineas_detalle
                        if l.get("concepto", "").lower() not in [
                            "hospedaje", "estadia", "habitacion", "noche"
                        ]
                    ]

                    msg = pago_cuenta(
                        habitacion=hab_num,
                        monto_cuenta=self.total_a_pagar,
                        monto_abonado=total_pagado_usd,
                        pagos=self.pagos_sesion,
                        saldo_pendiente=saldo_pendiente_tx,
                        recepcionista=recep,
                        nombre=nombre_huesped,
                        cargos_extras=cargos_extras if cargos_extras else None,
                        es_abono=es_abono,
                    )
                    enviar_texto(msg)
                except Exception as _e:
                    print(f"[PaymentDialog] Error Telegram pago cuenta: {_e}")

            sesion.commit()
            self.pagina.close(self.dialogo)
            self.pagina.open(
                ft.SnackBar(
                    ft.Text(
                        "Cobro registrado correctamente"
                        if saldo_pendiente_tx <= 0.01
                        else f"Cobro parcial — Quedan ${saldo_pendiente_tx:.2f} pendientes"
                    ),
                    bgcolor=ft.Colors.GREEN_700
                    if saldo_pendiente_tx <= 0.01
                    else ft.Colors.BLUE_700,
                )
            )
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(
                ft.SnackBar(
                    ft.Text(f"Error al registrar el pago: {error}"),
                    bgcolor=ft.Colors.RED_700,
                )
            )
        finally:
            sesion.close()

    def mostrar(self):
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)
