# modules/rooms/checkout.py
#
# Wizard de Check-Out en 4 pasos:
#   Paso 1 — Resumen financiero: deuda o saldo a favor
#   Paso 2 — Gestión del saldo (cobrar deuda / entregar vuelto / dejar como crédito)
#   Paso 3 — Nota sobre la estadía + opción de lista negra
#   Paso 4 — Confirmación y cierre de la habitación (estado → LIMPIEZA)

import flet as ft
from datetime import datetime
from sqlalchemy.orm import selectinload
from database.connection import SesionLocal
from database.models import (
    Habitacion, Estadia, Huesped, Pago, Caja,
    MetodoPago, LineaCuenta, EstadoHabitacion,
)
from utils.calculos_financieros import leer_config_financiera, a_bs, a_usd

# ── Métodos de pago disponibles para vuelto / cobro ─────────────────────────
METODOS_VUELTO = {
    MetodoPago.CASH_USD:    {"etiqueta": "Efectivo $",     "icono": ft.Icons.ATTACH_MONEY,   "color": ft.Colors.GREEN_800,  "es_bs": False},
    MetodoPago.CASH_BS:     {"etiqueta": "Efectivo Bs",    "icono": ft.Icons.MONEY,           "color": ft.Colors.TEAL_700,   "es_bs": True},
    MetodoPago.TRANSFER_BS: {"etiqueta": "Transferencia",  "icono": ft.Icons.SWAP_HORIZ,      "color": ft.Colors.BLUE_700,   "es_bs": True},
    MetodoPago.PAGO_MOVIL:  {"etiqueta": "Pago Móvil",     "icono": ft.Icons.PHONE_ANDROID,   "color": ft.Colors.PURPLE_700, "es_bs": True},
    MetodoPago.ZELLE:       {"etiqueta": "Zelle",           "icono": ft.Icons.SEND,            "color": ft.Colors.INDIGO_700, "es_bs": False},
    MetodoPago.DEBIT_CARD:  {"etiqueta": "T. Débito",      "icono": ft.Icons.CREDIT_CARD,     "color": ft.Colors.ORANGE_700, "es_bs": False},
}

METODOS_COBRO = METODOS_VUELTO  # mismos métodos para cobrar deuda


class CheckOutWizard:
    """
    Wizard modal de Check-Out.

    al_completar : callback(habitacion) → se llama al finalizar con éxito.
    """

    def __init__(self, pagina: ft.Page, habitacion: Habitacion, al_completar):
        self.pagina       = pagina
        self.habitacion   = habitacion
        self.al_completar = al_completar
        self.dialogo      = None

        # Estado interno del wizard
        self._paso_actual   = 0          # 0..3
        self._estadia       = None
        self._titular       = None
        self._total_pendiente = 0.0      # deuda (> 0) o saldo a favor (< 0)
        self._pagos_cobro   = []         # pagos acumulados para saldar deuda
        self._decision_saldo = None      # 'credito' | 'vuelto' | 'registrar'
        self._pagos_vuelto  = []         # desglose del vuelto a entregar
        self._nota_estadia  = ""
        self._agregar_lista_negra = False
        self._motivo_veto   = ""

        # Widgets persistentes del contenedor del wizard
        self._titulo_paso   = ft.Text("", size=16, weight="bold")
        self._subtitulo     = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self._cuerpo        = ft.Container(expand=True)
        self._btn_siguiente = ft.ElevatedButton(
            "Siguiente →",
            bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
            on_click=self._siguiente,
        )
        self._btn_anterior  = ft.TextButton("← Atrás", on_click=self._anterior, visible=False)
        self._indicadores   = ft.Row(spacing=6)

        # Área de pagos de cobro (paso 2 deuda)
        self._col_pagos_cobro   = ft.Column(spacing=6)
        self._col_pagos_vuelto  = ft.Column(spacing=6)
        self._txt_pendiente_cobro = ft.Text("", weight="bold", size=13)

        # Cargar datos de la estadía
        self._cargar_datos()

    # ════════════════════════════════════════════════════════════════════════
    # CARGA DE DATOS
    # ════════════════════════════════════════════════════════════════════════

    def _cargar_datos(self):
        sesion = SesionLocal()
        try:
            estadia = (
                sesion.query(Estadia)
                .options(
                    selectinload(Estadia.huespedes),
                    selectinload(Estadia.lineas_cuenta),
                    selectinload(Estadia.pagos),
                )
                .filter(
                    Estadia.habitacion_id == self.habitacion.id,
                    Estadia.activa == True,
                )
                .first()
            )
            if not estadia:
                return

            self._estadia = estadia
            self._titular = estadia.huespedes[0] if estadia.huespedes else None

            # Calcular balance: positivo = deuda, negativo = saldo a favor
            pendiente   = sum(l.monto_usd for l in estadia.lineas_cuenta if not l.cancelada)
            total_pagado = sum(
                -p.monto_usd if p.es_devolucion else p.monto_usd
                for p in estadia.pagos
            )
            credito_titular = round(self._titular.credito_usd or 0.0, 2) if self._titular else 0.0

            # pendiente > 0 → cliente debe dinero
            # credito_titular > 0 → cliente tiene saldo a favor
            self._total_pendiente = round(pendiente, 2)
            self._credito_titular = credito_titular

        finally:
            sesion.close()

    # ════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN Y APERTURA
    # ════════════════════════════════════════════════════════════════════════

    def mostrar(self):
        if not self._estadia:
            self.pagina.open(ft.SnackBar(ft.Text("No se encontró estadía activa."), bgcolor="red"))
            return

        self._renderizar_paso()

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.EXIT_TO_APP, color=ft.Colors.RED_700, size=22),
                ft.Column([
                    ft.Text(f"Check-Out — Habitación {self.habitacion.numero}",
                            weight="bold", size=15),
                    ft.Text(self._titular.nombre_completo if self._titular else "",
                            size=11, color=ft.Colors.GREY_600),
                ], spacing=1),
                ft.Container(expand=True),
                self._indicadores,
            ], spacing=10),
            content=ft.Container(
                width=720, height=480,
                content=ft.Column([
                    ft.Container(
                        content=ft.Column([self._titulo_paso, self._subtitulo], spacing=2),
                        padding=ft.padding.only(bottom=12),
                        border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.GREY_200)),
                    ),
                    ft.Container(content=self._cuerpo, expand=True),
                ], spacing=12, expand=True),
            ),
            actions=[
                self._btn_anterior,
                ft.Container(expand=True),
                self._btn_siguiente,
            ],
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        self.pagina.open(self.dialogo)

    # ════════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN
    # ════════════════════════════════════════════════════════════════════════

    def _siguiente(self, evento):
        # Validar antes de avanzar
        if not self._validar_paso():
            return
        self._paso_actual += 1
        # Si en paso 2 no hay nada que gestionar, saltar al 3
        if self._paso_actual == 2 and not self._tiene_paso_2():
            self._paso_actual = 3
        if self._paso_actual > 3:
            self._ejecutar_checkout()
            return
        self._renderizar_paso()
        self.dialogo.update()

    def _anterior(self, evento):
        self._paso_actual -= 1
        if self._paso_actual == 2 and not self._tiene_paso_2():
            self._paso_actual = 1
        if self._paso_actual < 0:
            self._paso_actual = 0
        self._renderizar_paso()
        self.dialogo.update()

    def _tiene_paso_2(self) -> bool:
        """El paso 2 solo aparece si hay deuda o saldo a favor."""
        return self._total_pendiente > 0.01 or self._credito_titular > 0.01

    def _renderizar_paso(self):
        pasos = ["Resumen", "Balance", "Nota", "Confirmar"]
        # Si no hay paso 2, remover de la lista visual
        pasos_vis = pasos if self._tiene_paso_2() else ["Resumen", "Nota", "Confirmar"]

        self._indicadores.controls = [
            ft.Container(
                width=80, height=6,
                bgcolor=ft.Colors.BLUE_700 if i <= self._paso_actual else ft.Colors.GREY_300,
                border_radius=3,
            )
            for i in range(len(pasos))
        ]

        if self._paso_actual == 0:
            self._renderizar_paso_0()
        elif self._paso_actual == 1:
            self._renderizar_paso_1()
        elif self._paso_actual == 2:
            self._renderizar_paso_2()  # deuda o saldo
        elif self._paso_actual == 3:
            self._renderizar_paso_3()

        self._btn_anterior.visible = self._paso_actual > 0
        ultimo = 3
        self._btn_siguiente.text  = "Finalizar Check-Out ✓" if self._paso_actual == ultimo else "Siguiente →"
        self._btn_siguiente.bgcolor = ft.Colors.RED_700 if self._paso_actual == ultimo else ft.Colors.BLUE_700

    def _validar_paso(self) -> bool:
        if self._paso_actual == 2:
            # Validar que la deuda o el vuelto estén gestionados
            if self._total_pendiente > 0.01:
                return self._validar_cobro_deuda()
            elif self._credito_titular > 0.01:
                return self._validar_decision_saldo()
        return True

    # ════════════════════════════════════════════════════════════════════════
    # PASO 0 — RESUMEN FINANCIERO
    # ════════════════════════════════════════════════════════════════════════

    def _renderizar_paso_0(self):
        self._titulo_paso.value = "Resumen de la Estadía"
        self._subtitulo.value   = "Revisa el estado financiero antes de cerrar."

        sesion = SesionLocal()
        try:
            config = leer_config_financiera(sesion)
            tasa   = config.tasa_cambio
        finally:
            sesion.close()

        estadia = self._estadia
        titular = self._titular
        noches  = (estadia.salida - estadia.entrada).days if estadia.salida else 0

        # ── Tarjeta del huésped ──────────────────────────────────────────
        info_huesped = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.PERSON, color=ft.Colors.BLUE_700, size=16),
                        ft.Text(titular.nombre_completo if titular else "N/A",
                                weight="bold", size=14),
                        # Badge lista negra
                        ft.Container(
                            content=ft.Text("⚠ VETADO", size=9, color=ft.Colors.WHITE,
                                            weight="bold"),
                            bgcolor=ft.Colors.RED_700,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=4,
                            visible=titular.lista_negra if titular else False,
                        ),
                    ], spacing=6),
                    ft.Text(f"Doc: {titular.documento}" if titular else "",
                            size=11, color=ft.Colors.GREY_600),
                    ft.Text(
                        f"Estadía: {estadia.entrada.strftime('%d/%m/%Y')} → "
                        f"{estadia.salida.strftime('%d/%m/%Y')} ({noches} noche{'s' if noches != 1 else ''})",
                        size=11, color=ft.Colors.GREY_600,
                    ),
                ], spacing=3, expand=True),
            ]),
            bgcolor=ft.Colors.BLUE_50,
            padding=12, border_radius=10,
            border=ft.border.all(1, ft.Colors.BLUE_100),
        )

        # ── Indicadores financieros ──────────────────────────────────────
        def _chip(label, valor, color, icono):
            return ft.Container(
                content=ft.Column([
                    ft.Row([ft.Icon(icono, size=14, color=color),
                            ft.Text(label, size=10, color=ft.Colors.GREY_600)], spacing=4),
                    ft.Text(valor, size=18, weight="bold", color=color),
                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.with_opacity(0.07, color),
                padding=ft.padding.symmetric(horizontal=20, vertical=12),
                border_radius=10,
                border=ft.border.all(1, ft.Colors.with_opacity(0.2, color)),
                expand=True,
            )

        # Estado del balance
        if self._total_pendiente > 0.01:
            estado = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.RED_700, size=20),
                    ft.Column([
                        ft.Text("El huésped tiene cuentas pendientes.", weight="bold",
                                color=ft.Colors.RED_700, size=13),
                        ft.Text(
                            "En el siguiente paso podrás cobrar la deuda o "
                            "registrarla para futuras estadías.",
                            size=11, color=ft.Colors.RED_600,
                        ),
                    ], spacing=2),
                ], spacing=10),
                bgcolor=ft.Colors.RED_50, padding=12, border_radius=8,
                border=ft.border.all(1, ft.Colors.RED_200),
            )
        elif self._credito_titular > 0.01:
            estado = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.GREEN_700, size=20),
                    ft.Column([
                        ft.Text("El huésped tiene saldo a favor.", weight="bold",
                                color=ft.Colors.GREEN_700, size=13),
                        ft.Text(
                            "En el siguiente paso podrás entregar el vuelto "
                            "o dejarlo como crédito para futuras estadías.",
                            size=11, color=ft.Colors.GREEN_600,
                        ),
                    ], spacing=2),
                ], spacing=10),
                bgcolor=ft.Colors.GREEN_50, padding=12, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREEN_200),
            )
        else:
            estado = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700, size=20),
                    ft.Text("Cuenta saldada. No hay deuda ni saldo pendiente.",
                            weight="bold", color=ft.Colors.GREEN_700, size=13),
                ], spacing=10),
                bgcolor=ft.Colors.GREEN_50, padding=12, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREEN_200),
            )

        lineas_pendientes = [l for l in estadia.lineas_cuenta if not l.cancelada]
        total_pagado = sum(-p.monto_usd if p.es_devolucion else p.monto_usd
                          for p in estadia.pagos)

        chips = ft.Row([
            _chip("Cargos totales",   f"${self._total_pendiente:.2f}",
                  ft.Colors.RED_700 if self._total_pendiente > 0.01 else ft.Colors.GREY_500,
                  ft.Icons.RECEIPT_LONG),
            _chip("Total pagado",     f"${total_pagado:.2f}",    ft.Colors.GREEN_700, ft.Icons.PAYMENTS),
            _chip("Saldo a favor",    f"${self._credito_titular:.2f}",
                  ft.Colors.BLUE_700 if self._credito_titular > 0.01 else ft.Colors.GREY_500,
                  ft.Icons.ACCOUNT_BALANCE_WALLET),
        ], spacing=10)

        self._cuerpo.content = ft.Column([
            info_huesped,
            chips,
            estado,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    # ════════════════════════════════════════════════════════════════════════
    # PASO 1 → PASO 2 dependiendo de la situación financiera
    # PASO 2 — GESTIÓN DEL BALANCE (deuda o vuelto)
    # ════════════════════════════════════════════════════════════════════════

    def _renderizar_paso_2(self):
        if self._total_pendiente > 0.01:
            self._renderizar_cobro_deuda()
        elif self._credito_titular > 0.01:
            self._renderizar_gestion_vuelto()

    # ── 2a. Cobro de deuda ───────────────────────────────────────────────

    def _renderizar_cobro_deuda(self):
        sesion = SesionLocal()
        try:
            config = leer_config_financiera(sesion)
            tasa   = config.tasa_cambio
        finally:
            sesion.close()

        self._tasa = tasa
        self._titulo_paso.value = "Gestión de Deuda Pendiente"
        self._subtitulo.value   = (
            f"El huésped debe ${self._total_pendiente:.2f}. "
            "Cobra ahora o registra la deuda para futuras estadías."
        )

        # Opción rápida: registrar deuda sin cobrar
        self._radio_deuda = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="cobrar",    label="Cobrar la deuda ahora"),
                ft.Radio(value="registrar", label="Registrar como deuda del cliente (para futuras estadías)"),
            ]),
            value="cobrar",
            on_change=self._cambiar_modo_deuda,
        )

        # Panel de cobro (igual que DialogoPago pero simplificado)
        self._area_cobro = ft.Column(spacing=8, visible=True)
        self._area_registro = ft.Container(
            visible=False,
            content=ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.PENDING_ACTIONS, size=40, color=ft.Colors.ORANGE_400),
                    ft.Text(
                        f"Se registrará una deuda de ${self._total_pendiente:.2f}\n"
                        "en el perfil del huésped.\nSi regresa, se le cargará automáticamente.",
                        text_align=ft.TextAlign.CENTER,
                        size=13, color=ft.Colors.GREY_700,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                padding=20, alignment=ft.alignment.center,
            ),
        )
        self._construir_panel_cobro(tasa)

        self._cuerpo.content = ft.Column([
            ft.Container(
                content=self._radio_deuda,
                bgcolor=ft.Colors.ORANGE_50, padding=12, border_radius=8,
                border=ft.border.all(1, ft.Colors.ORANGE_200),
            ),
            self._area_cobro,
            self._area_registro,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    def _construir_panel_cobro(self, tasa):
        """Panel de métodos de pago para cobrar la deuda."""
        self._txt_pendiente_cobro.value = f"Pendiente: ${self._total_pendiente:.2f}"
        self._txt_pendiente_cobro.color = ft.Colors.RED_700
        self._col_pagos_cobro.controls  = []
        self._pagos_cobro               = []

        botones = [
            ft.ElevatedButton(
                text=cfg["etiqueta"], icon=cfg["icono"],
                style=ft.ButtonStyle(
                    color=cfg["color"],
                    bgcolor=ft.Colors.with_opacity(0.07, cfg["color"]),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    side=ft.BorderSide(1.2, ft.Colors.with_opacity(0.3, cfg["color"])),
                ),
                height=40,
                on_click=lambda _, m=metodo: self._seleccionar_metodo_cobro(m, tasa),
            )
            for metodo, cfg in METODOS_COBRO.items()
        ]

        self._area_cobro.controls = [
            ft.Row(controls=botones, wrap=True, spacing=8, run_spacing=8),
            ft.Divider(height=1),
            self._txt_pendiente_cobro,
            self._col_pagos_cobro,
        ]

    def _seleccionar_metodo_cobro(self, metodo, tasa):
        cfg   = METODOS_COBRO[metodo]
        es_bs = cfg["es_bs"]
        pendiente_restante = self._pendiente_cobro_restante()
        valor_sug = (
            f"{a_bs(pendiente_restante, tasa):.2f}" if es_bs
            else f"{pendiente_restante:.2f}"
        )
        campo   = ft.TextField(
            label=f"Monto ({'Bs.' if es_bs else '$'})",
            value=valor_sug,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True, expand=True,
        )
        campo_ref = ft.TextField(
            label="Referencia",
            visible=metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS],
            expand=True,
        )

        def agregar(_):
            try:
                valor     = float(campo.value.replace(",", ".") or 0)
                monto_usd = a_usd(valor, tasa) if es_bs else valor
                monto_bs  = valor if es_bs else a_bs(valor, tasa)
                self._pagos_cobro.append({
                    "metodo": metodo, "monto_usd": round(monto_usd, 2),
                    "monto_bs": round(monto_bs, 2),
                    "referencia": campo_ref.value.strip(),
                    "etiqueta": cfg["etiqueta"], "color": cfg["color"],
                    "icono": cfg["icono"], "es_bs": es_bs,
                    "visualizacion": f"Bs. {valor:,.2f}" if es_bs else f"${valor:.2f}",
                })
                self._refrescar_cobro(tasa)
            except ValueError:
                campo.error_text = "Número inválido"
                campo.update()

        dlg_metodo = ft.AlertDialog(
            title=ft.Row([ft.Icon(cfg["icono"], color=cfg["color"]), ft.Text(cfg["etiqueta"])]),
            content=ft.Container(
                width=380,
                content=ft.Column([
                    ft.Row([campo, campo_ref] if metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS] else [campo]),
                ], tight=True, spacing=10),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg_metodo)),
                ft.ElevatedButton("Agregar", bgcolor=cfg["color"], color="white", on_click=lambda _: (self.pagina.close(dlg_metodo), agregar(None))),
            ],
        )
        self.pagina.open(dlg_metodo)

    def _pendiente_cobro_restante(self) -> float:
        abonado = sum(p["monto_usd"] for p in self._pagos_cobro)
        return round(max(0.0, self._total_pendiente - abonado), 2)

    def _refrescar_cobro(self, tasa):
        restante = self._pendiente_cobro_restante()
        self._txt_pendiente_cobro.value = (
            f"✓ Deuda saldada" if restante <= 0.01
            else f"Pendiente: ${restante:.2f}  ·  Bs. {a_bs(restante, tasa):,.2f}"
        )
        self._txt_pendiente_cobro.color = (
            ft.Colors.GREEN_700 if restante <= 0.01 else ft.Colors.RED_700
        )
        self._col_pagos_cobro.controls = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(p["icono"], size=14, color=p["color"]),
                    ft.Text(p["etiqueta"], size=12, expand=True),
                    ft.Text(p["visualizacion"], size=12, weight="bold"),
                    ft.IconButton(
                        ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_size=15,
                        icon_color=ft.Colors.RED_400,
                        on_click=lambda _, i=idx: (self._pagos_cobro.pop(i), self._refrescar_cobro(tasa)),
                    ),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                bgcolor=ft.Colors.with_opacity(0.06, p["color"]), border_radius=7,
            )
            for idx, p in enumerate(self._pagos_cobro)
        ]
        self.pagina.update()

    def _cambiar_modo_deuda(self, evento):
        modo = self._radio_deuda.value
        self._area_cobro.visible    = (modo == "cobrar")
        self._area_registro.visible = (modo == "registrar")
        self.pagina.update()

    def _validar_cobro_deuda(self) -> bool:
        if not hasattr(self, "_radio_deuda"):
            return True
        if self._radio_deuda.value == "registrar":
            self._decision_saldo = "registrar"
            return True
        if self._pendiente_cobro_restante() > 0.01:
            self.pagina.open(ft.SnackBar(
                ft.Text("Aún hay monto pendiente por cobrar. Agrega pagos o elige 'Registrar deuda'."),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return False
        self._decision_saldo = "cobrar"
        return True

    # ── 2b. Gestión del saldo a favor (vuelto o crédito) ─────────────────

    def _renderizar_gestion_vuelto(self):
        sesion = SesionLocal()
        try:
            config = leer_config_financiera(sesion)
            tasa   = config.tasa_cambio
        finally:
            sesion.close()

        self._tasa = tasa
        self._titulo_paso.value = "Gestión de Saldo a Favor"
        self._subtitulo.value   = (
            f"El huésped tiene ${self._credito_titular:.2f} a su favor. "
            "¿Qué deseas hacer con ese saldo?"
        )

        self._radio_vuelto = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(
                    value="credito",
                    label=f"Conservar ${self._credito_titular:.2f} como crédito para futuras estadías",
                ),
                ft.Radio(
                    value="vuelto",
                    label="Entregar el vuelto ahora",
                ),
            ]),
            value="credito",
            on_change=self._cambiar_modo_vuelto,
        )

        self._panel_vuelto = ft.Column(visible=False, spacing=8)
        self._construir_panel_vuelto(tasa)

        self._cuerpo.content = ft.Column([
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET,
                                color=ft.Colors.GREEN_700, size=18),
                        ft.Text(f"Saldo a favor del titular: ${self._credito_titular:.2f}",
                                weight="bold", color=ft.Colors.GREEN_700),
                    ], spacing=6),
                ]),
                bgcolor=ft.Colors.GREEN_50, padding=12, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREEN_200),
            ),
            ft.Container(
                content=self._radio_vuelto,
                bgcolor=ft.Colors.GREY_50, padding=12, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREY_200),
            ),
            self._panel_vuelto,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    def _construir_panel_vuelto(self, tasa):
        """Panel para desglosar cómo se entrega el vuelto (igual que en payment_dialog)."""
        sobrante_usd = self._credito_titular
        sobrante_bs  = a_bs(sobrante_usd, tasa)
        self._pagos_vuelto = []

        self._col_pagos_vuelto.controls = []
        txt_total_vuelto = ft.Text(
            f"Total a devolver: ${sobrante_usd:.2f}  ·  Bs. {sobrante_bs:,.2f}",
            size=12, color=ft.Colors.GREY_700,
        )

        botones_vuelto = [
            ft.ElevatedButton(
                text=cfg["etiqueta"], icon=cfg["icono"],
                style=ft.ButtonStyle(
                    color=cfg["color"],
                    bgcolor=ft.Colors.with_opacity(0.07, cfg["color"]),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    side=ft.BorderSide(1.2, ft.Colors.with_opacity(0.3, cfg["color"])),
                ),
                height=40,
                on_click=lambda _, m=metodo: self._agregar_vuelto(m, tasa),
            )
            for metodo, cfg in METODOS_VUELTO.items()
        ]

        self._txt_vuelto_restante = ft.Text("", size=12)

        self._panel_vuelto.controls = [
            ft.Text("Selecciona cómo entregar el vuelto:", size=12, color=ft.Colors.GREY_700),
            txt_total_vuelto,
            ft.Row(controls=botones_vuelto, wrap=True, spacing=8, run_spacing=8),
            ft.Divider(height=1),
            self._txt_vuelto_restante,
            self._col_pagos_vuelto,
        ]
        self._refrescar_vuelto(tasa)

    def _agregar_vuelto(self, metodo, tasa):
        cfg   = METODOS_VUELTO[metodo]
        es_bs = cfg["es_bs"]
        restante = self._vuelto_restante()
        valor_sug = (
            f"{a_bs(restante, tasa):.2f}" if es_bs
            else f"{restante:.2f}"
        )
        campo = ft.TextField(
            label=f"Monto ({'Bs.' if es_bs else '$'})",
            value=valor_sug,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True, expand=True,
        )

        def confirmar(_):
            try:
                valor     = float(campo.value.replace(",", ".") or 0)
                monto_usd = a_usd(valor, tasa) if es_bs else valor
                monto_bs  = valor if es_bs else a_bs(valor, tasa)
                if round(monto_usd, 2) > self._credito_titular + 0.01:
                    self.pagina.open(ft.SnackBar(
                        ft.Text(f"No puedes devolver más del saldo disponible (${self._credito_titular:.2f})"),
                        bgcolor=ft.Colors.RED_700,
                    ))
                    return
                self._pagos_vuelto.append({
                    "metodo": metodo, "monto_usd": round(monto_usd, 2),
                    "monto_bs": round(monto_bs, 2),
                    "etiqueta": cfg["etiqueta"], "color": cfg["color"],
                    "icono": cfg["icono"], "es_bs": es_bs,
                    "visualizacion": f"Bs. {valor:,.2f}" if es_bs else f"${valor:.2f}",
                })
                self._refrescar_vuelto(tasa)
            except ValueError:
                campo.error_text = "Número inválido"
                campo.update()

        dlg = ft.AlertDialog(
            title=ft.Row([ft.Icon(cfg["icono"], color=cfg["color"]), ft.Text(cfg["etiqueta"])]),
            content=ft.Container(width=340, content=ft.Column([campo], tight=True)),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton("Agregar", bgcolor=cfg["color"], color="white",
                                  on_click=lambda _: (self.pagina.close(dlg), confirmar(None))),
            ],
        )
        self.pagina.open(dlg)

    def _vuelto_restante(self) -> float:
        devuelto = sum(p["monto_usd"] for p in self._pagos_vuelto)
        return round(max(0.0, self._credito_titular - devuelto), 2)

    def _refrescar_vuelto(self, tasa):
        restante = self._vuelto_restante()
        self._txt_vuelto_restante.value = (
            f"✓ Vuelto completo" if restante <= 0.01
            else f"Falta distribuir: ${restante:.2f}  ·  Bs. {a_bs(restante, tasa):,.2f}"
        )
        self._txt_vuelto_restante.color = (
            ft.Colors.GREEN_700 if restante <= 0.01 else ft.Colors.ORANGE_700
        )
        self._col_pagos_vuelto.controls = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(p["icono"], size=14, color=p["color"]),
                    ft.Text(p["etiqueta"], size=12, expand=True),
                    ft.Text(p["visualizacion"], size=12, weight="bold"),
                    ft.IconButton(
                        ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_size=15,
                        icon_color=ft.Colors.RED_400,
                        on_click=lambda _, i=idx: (self._pagos_vuelto.pop(i), self._refrescar_vuelto(tasa)),
                    ),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                bgcolor=ft.Colors.with_opacity(0.06, p["color"]), border_radius=7,
            )
            for idx, p in enumerate(self._pagos_vuelto)
        ]
        self.pagina.update()

    def _cambiar_modo_vuelto(self, evento):
        self._panel_vuelto.visible = (self._radio_vuelto.value == "vuelto")
        self.pagina.update()

    def _validar_decision_saldo(self) -> bool:
        if not hasattr(self, "_radio_vuelto"):
            return True
        if self._radio_vuelto.value == "credito":
            self._decision_saldo = "credito"
            return True
        # modo vuelto: validar que el desglose cuadre
        if self._vuelto_restante() > 0.01:
            self.pagina.open(ft.SnackBar(
                ft.Text("Debes distribuir el vuelto completo o elegir 'Conservar como crédito'."),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return False
        self._decision_saldo = "vuelto"
        return True

    # ════════════════════════════════════════════════════════════════════════
    # PASO 1 (sin paso 2) / PASO 3 — NOTA Y LISTA NEGRA
    # Cuando no hay balance, el paso 1 es el paso de notas.
    # ════════════════════════════════════════════════════════════════════════

    def _renderizar_paso_1(self):
        # paso 1 es simplemente ir a paso 2 si existe, si no skip
        # Aquí lo redirigimos al paso de nota cuando no hay paso 2
        if not self._tiene_paso_2():
            self._renderizar_paso_nota()
        else:
            self._renderizar_paso_2()

    def _renderizar_paso_3(self):
        self._renderizar_paso_nota()

    def _renderizar_paso_nota(self):
        self._titulo_paso.value = "Nota de la Estadía"
        self._subtitulo.value   = "Añade observaciones y revisa el estado del huésped."

        self._campo_nota = ft.TextField(
            label="Nota sobre la estadía (opcional)",
            multiline=True, min_lines=4, max_lines=6,
            hint_text="Comportamiento, preferencias, incidencias, observaciones...",
            value=self._nota_estadia,
            on_change=lambda e: setattr(self, "_nota_estadia", e.control.value),
        )

        self._switch_lista_negra = ft.Switch(
            label="Agregar a lista negra",
            value=self._agregar_lista_negra,
            active_color=ft.Colors.RED_700,
            on_change=self._cambiar_lista_negra,
        )

        self._campo_motivo_veto = ft.TextField(
            label="Motivo del veto",
            hint_text="Describe el motivo...",
            value=self._motivo_veto,
            visible=self._agregar_lista_negra,
            multiline=True, min_lines=2, max_lines=3,
            on_change=lambda e: setattr(self, "_motivo_veto", e.control.value),
        )

        self._cuerpo.content = ft.Column([
            self._campo_nota,
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.BLOCK, color=ft.Colors.RED_700, size=18),
                        ft.Text("Lista negra", weight="bold", size=13),
                    ], spacing=6),
                    ft.Text(
                        "Si se activa, el huésped quedará marcado como vetado "
                        "y el sistema mostrará una advertencia si intenta registrarse de nuevo.",
                        size=11, color=ft.Colors.GREY_600,
                    ),
                    self._switch_lista_negra,
                    self._campo_motivo_veto,
                ], spacing=8),
                bgcolor=ft.Colors.RED_50, padding=14, border_radius=10,
                border=ft.border.all(1, ft.Colors.RED_100),
            ),
        ], spacing=12, scroll=ft.ScrollMode.AUTO)

    def _cambiar_lista_negra(self, evento):
        self._agregar_lista_negra = self._switch_lista_negra.value
        self._campo_motivo_veto.visible = self._agregar_lista_negra
        self.pagina.update()

    # ════════════════════════════════════════════════════════════════════════
    # PASO FINAL — CONFIRMACIÓN VISUAL
    # ════════════════════════════════════════════════════════════════════════

    # El paso 3 siempre es nota, así que el último paso disponible en el
    # wizard es siempre el 3. Al pulsar "Finalizar" desde el paso 3
    # se ejecuta directamente el checkout.

    # ════════════════════════════════════════════════════════════════════════
    # EJECUCIÓN DEL CHECKOUT
    # ════════════════════════════════════════════════════════════════════════

    def _ejecutar_checkout(self):
        sesion = SesionLocal()
        try:
            config = leer_config_financiera(sesion)
            tasa   = config.tasa_cambio

            estadia_bd = sesion.get(Estadia, self._estadia.id)
            hab_bd     = sesion.get(Habitacion, self.habitacion.id)
            titular_bd = sesion.get(Huesped, self._titular.id) if self._titular else None
            caja       = sesion.query(Caja).first()

            # ── A. Registrar nota de la estadía ──────────────────────────
            if self._nota_estadia.strip():
                estadia_bd.notas = self._nota_estadia.strip()

            # ── B. Lista negra ────────────────────────────────────────────
            if titular_bd and self._agregar_lista_negra:
                titular_bd.lista_negra = True
                if self._motivo_veto.strip():
                    titular_bd.motivo_veto = self._motivo_veto.strip()

            # ── C. Gestión financiera ─────────────────────────────────────
            if self._total_pendiente > 0.01:
                if self._decision_saldo == "cobrar":
                    # Registrar los pagos recibidos y descontar caja si aplica
                    for pago in self._pagos_cobro:
                        sesion.add(Pago(
                            estadia_id  = estadia_bd.id,
                            monto_usd   = pago["monto_usd"],
                            monto_bs    = pago["monto_bs"],
                            tasa_cambio = tasa,
                            metodo      = pago["metodo"],
                            referencia  = pago.get("referencia", ""),
                            descripcion = "Cobro de deuda en Check-Out",
                            creado_en   = datetime.now(),
                            es_devolucion=False,
                        ))
                        if pago["metodo"] in [MetodoPago.CASH_USD, MetodoPago.ZELLE, MetodoPago.DEBIT_CARD]:
                            if caja: caja.saldo_principal_usd += pago["monto_usd"]
                        else:
                            if caja: caja.saldo_principal_bs  += pago["monto_bs"]

                    # Marcar todas las líneas pendientes como canceladas
                    for linea in estadia_bd.lineas_cuenta:
                        if not linea.cancelada:
                            linea.cancelada = True

                elif self._decision_saldo == "registrar":
                    # Guardar la deuda en el crédito negativo del titular
                    # (usamos un campo de deuda: reducimos credito_usd)
                    if titular_bd:
                        titular_bd.credito_usd = (titular_bd.credito_usd or 0.0) - self._total_pendiente

            elif self._credito_titular > 0.01:
                if self._decision_saldo == "vuelto":
                    # Registrar los vueltos y descontar de caja
                    for pago in self._pagos_vuelto:
                        # Verificar fondos
                        if pago["metodo"] in [MetodoPago.CASH_USD, MetodoPago.ZELLE, MetodoPago.DEBIT_CARD]:
                            if caja and caja.saldo_principal_usd < pago["monto_usd"]:
                                # Intentar de caja chica
                                if caja.caja_chica_usd >= pago["monto_usd"]:
                                    caja.caja_chica_usd -= pago["monto_usd"]
                                else:
                                    raise Exception(f"Fondos insuficientes en caja para devolver ${pago['monto_usd']:.2f}")
                            elif caja:
                                caja.saldo_principal_usd -= pago["monto_usd"]
                        else:
                            if caja and caja.saldo_principal_bs < pago["monto_bs"]:
                                if caja.caja_chica_bs >= pago["monto_bs"]:
                                    caja.caja_chica_bs -= pago["monto_bs"]
                                else:
                                    raise Exception(f"Fondos insuficientes en caja para devolver Bs. {pago['monto_bs']:,.2f}")
                            elif caja:
                                caja.saldo_principal_bs -= pago["monto_bs"]

                        sesion.add(Pago(
                            estadia_id   = estadia_bd.id,
                            monto_usd    = pago["monto_usd"],
                            monto_bs     = pago["monto_bs"],
                            tasa_cambio  = tasa,
                            metodo       = pago["metodo"],
                            descripcion  = "Vuelto entregado en Check-Out",
                            creado_en    = datetime.now(),
                            es_devolucion= True,
                        ))

                    # Limpiar el crédito (ya se devolvió)
                    if titular_bd:
                        titular_bd.credito_usd = 0.0

                # Si decision_saldo == 'credito': no se hace nada, el crédito queda en Huesped

            # ── D. Cerrar estadía ─────────────────────────────────────────
            estadia_bd.activa = False

            # ── E. Habitación → LIMPIEZA (no FREE) ────────────────────────
            hab_bd.estado = EstadoHabitacion.CLEANING

            sesion.commit()

            self.pagina.close(self.dialogo)
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Check-Out Hab. {self.habitacion.numero} completado. Estado → Limpieza."),
                bgcolor=ft.Colors.GREEN_700,
                duration=4000,
            ))
            if self.al_completar:
                self.al_completar(self.habitacion)

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error en Check-Out: {error}"), bgcolor=ft.Colors.RED_700
            ))
        finally:
            sesion.close()
            