# modules/rooms/checkout.py
#
# Wizard de Check-Out — 3 pasos:
#   Paso 0 — Resumen financiero
#   Paso 1 — Gestión del balance (deuda o saldo a favor)  ← solo si aplica
#   Paso 2 — Nota + lista negra
#
# REGLA FLET 0.28.3 aplicada aquí:
#   NUNCA se llama pagina.open() para sub-diálogos dentro del wizard.
#   Los formularios de monto se muestran INLINE reemplazando el contenido
#   del cuerpo del wizard, igual que el buscador externo en payment_dialog.
#   Esto evita que pagina.close() cierre el wizard por error.

import flet as ft
from datetime import datetime
from sqlalchemy.orm import selectinload
from database.connection import SesionLocal
from database.models import (
    Habitacion, Estadia, Huesped, Pago, Caja,
    MetodoPago, LineaCuenta, EstadoHabitacion,
)
from utils.calculos_financieros import leer_config_financiera, a_bs, a_usd
from modules.finance.gestor_vuelto import GestorVuelto

METODOS = {
    MetodoPago.CASH_USD:    {"etiqueta": "Efectivo $",    "icono": ft.Icons.ATTACH_MONEY,  "color": ft.Colors.GREEN_800,  "es_bs": False},
    MetodoPago.CASH_BS:     {"etiqueta": "Efectivo Bs",   "icono": ft.Icons.MONEY,          "color": ft.Colors.TEAL_700,   "es_bs": True},
    MetodoPago.TRANSFER_BS: {"etiqueta": "Transferencia", "icono": ft.Icons.SWAP_HORIZ,     "color": ft.Colors.BLUE_700,   "es_bs": True},
    MetodoPago.PAGO_MOVIL:  {"etiqueta": "Pago Móvil",    "icono": ft.Icons.PHONE_ANDROID,  "color": ft.Colors.PURPLE_700, "es_bs": True},
    MetodoPago.ZELLE:       {"etiqueta": "Zelle",          "icono": ft.Icons.SEND,           "color": ft.Colors.INDIGO_700, "es_bs": False},
    MetodoPago.DEBIT_CARD:  {"etiqueta": "T. Débito",     "icono": ft.Icons.CREDIT_CARD,    "color": ft.Colors.ORANGE_700, "es_bs": False},
}


class CheckOutWizard:
    """
    Wizard modal de Check-Out.
    Todos los sub-formularios son INLINE para evitar diálogos anidados.
    """

    def __init__(self, pagina: ft.Page, habitacion: Habitacion, al_completar):
        self.pagina       = pagina
        self.habitacion   = habitacion
        self.al_completar = al_completar
        self.dialogo      = None

        # ── Estado del wizard ────────────────────────────────────────────
        self._paso        = 0
        self._estadia     = None
        self._titular     = None
        self._total_pend  = 0.0   # cargos sin pagar
        self._credito     = 0.0   # saldo a favor del titular
        self._tasa        = 35.5

        self._pagos_cobro  = []   # para saldar deuda
        self._pagos_vuelto = []   # para entregar vuelto
        self._decision     = None  # 'cobrar' | 'registrar' | 'vuelto' | 'credito'
        self._gestor_vuelto = None  # GestorVuelto — se crea en _paso_vuelto
        self._nota         = ""
        self._lista_negra  = False
        self._motivo_veto  = ""

        # ── Widgets persistentes (viven toda la sesión del wizard) ───────
        self._titulo   = ft.Text("", size=16, weight="bold")
        self._subtit   = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self._cuerpo   = ft.Container(expand=True)
        self._indicadores = ft.Row(spacing=6)

        self._btn_cancelar  = ft.TextButton(
            "✕ Cancelar Check-Out",
            style=ft.ButtonStyle(color=ft.Colors.RED_400),
            on_click=self._cancelar,
        )
        self._btn_atras = ft.TextButton("← Atrás", on_click=self._atras, visible=False)
        self._btn_sig   = ft.ElevatedButton(
            "Siguiente →",
            bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
            on_click=self._siguiente,
        )

        self._cargar_datos()

    # ════════════════════════════════════════════════════════════════════
    # DATOS
    # ════════════════════════════════════════════════════════════════════

    def _cargar_datos(self):
        sesion = SesionLocal()
        try:
            config = leer_config_financiera(sesion)
            self._tasa = config.tasa_cambio

            est = (
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
            if not est:
                return
            self._estadia  = est
            self._titular  = est.huespedes[0] if est.huespedes else None
            self._total_pend = round(sum(l.monto_usd for l in est.lineas_cuenta if not l.cancelada), 2)
            self._credito    = round(self._titular.credito_usd or 0.0, 2) if self._titular else 0.0
        finally:
            sesion.close()

    # ════════════════════════════════════════════════════════════════════
    # APERTURA
    # ════════════════════════════════════════════════════════════════════

    def mostrar(self):
        if not self._estadia:
            self.pagina.open(ft.SnackBar(ft.Text("No se encontró estadía activa."), bgcolor="red"))
            return

        self._render()

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.EXIT_TO_APP, color=ft.Colors.RED_700, size=22),
                ft.Column([
                    ft.Text(f"Check-Out — Hab. {self.habitacion.numero}",
                            weight="bold", size=15),
                    ft.Text(self._titular.nombre_completo if self._titular else "",
                            size=11, color=ft.Colors.GREY_600),
                ], spacing=1),
                ft.Container(expand=True),
                self._indicadores,
            ], spacing=10),
            content=ft.Container(
                width=740, height=490,
                content=ft.Column([
                    ft.Container(
                        content=ft.Column([self._titulo, self._subtit], spacing=2),
                        padding=ft.padding.only(bottom=10),
                        border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.GREY_200)),
                    ),
                    ft.Container(content=self._cuerpo, expand=True),
                ], spacing=10, expand=True),
            ),
            actions=[
                self._btn_cancelar,
                self._btn_atras,
                ft.Container(expand=True),
                self._btn_sig,
            ],
            actions_alignment=ft.MainAxisAlignment.START,
            shape=ft.RoundedRectangleBorder(radius=14),
        )
        self.pagina.open(self.dialogo)

    # ════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN
    # ════════════════════════════════════════════════════════════════════

    def _cancelar(self, _):
        self.pagina.close(self.dialogo)

    def _siguiente(self, _):
        if not self._validar():
            return
        self._paso += 1
        if self._paso == 1 and not self._hay_paso_balance():
            self._paso = 2
        if self._paso > 2:
            self._ejecutar()
            return
        self._render()
        self.dialogo.update()

    def _atras(self, _):
        self._paso -= 1
        if self._paso == 1 and not self._hay_paso_balance():
            self._paso = 0
        if self._paso < 0:
            self._paso = 0
        self._render()
        self.dialogo.update()

    def _hay_paso_balance(self):
        return self._total_pend > 0.01 or self._credito > 0.01

    def _total_pasos(self):
        return 3 if self._hay_paso_balance() else 2

    def _render(self):
        n = self._total_pasos()
        self._indicadores.controls = [
            ft.Container(
                width=70, height=6, border_radius=3,
                bgcolor=ft.Colors.BLUE_700 if i <= self._paso else ft.Colors.GREY_300,
            )
            for i in range(n)
        ]
        self._btn_atras.visible = self._paso > 0
        es_ultimo = (self._paso == n - 1)
        self._btn_sig.text   = "Finalizar Check-Out ✓" if es_ultimo else "Siguiente →"
        self._btn_sig.bgcolor = ft.Colors.RED_700 if es_ultimo else ft.Colors.BLUE_700

        if self._paso == 0:
            self._paso_resumen()
        elif self._paso == 1 and self._hay_paso_balance():
            self._paso_balance()
        else:
            self._paso_nota()

    def _validar(self) -> bool:
        if self._paso == 1 and self._hay_paso_balance():
            if self._total_pend > 0.01:
                return self._validar_deuda()
            else:
                return self._validar_vuelto()
        return True

    # ════════════════════════════════════════════════════════════════════
    # PASO 0 — RESUMEN
    # ════════════════════════════════════════════════════════════════════

    def _paso_resumen(self):
        self._titulo.value = "Resumen de la Estadía"
        self._subtit.value  = "Revisa el estado financiero antes de continuar."

        est     = self._estadia
        titular = self._titular
        noches  = (est.salida - est.entrada).days if est.salida else 0
        total_pagado = sum(
            -p.monto_usd if p.es_devolucion else p.monto_usd
            for p in est.pagos
        )

        def chip(label, valor, color, icono):
            return ft.Container(
                content=ft.Column([
                    ft.Row([ft.Icon(icono, size=13, color=color),
                            ft.Text(label, size=10, color=ft.Colors.GREY_600)], spacing=4),
                    ft.Text(valor, size=17, weight="bold", color=color),
                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.with_opacity(0.07, color),
                padding=ft.padding.symmetric(horizontal=16, vertical=10),
                border_radius=10,
                border=ft.border.all(1, ft.Colors.with_opacity(0.2, color)),
                expand=True,
            )

        if self._total_pend > 0.01:
            banner = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.RED_700, size=18),
                    ft.Column([
                        ft.Text("Hay cargos pendientes sin pagar.", weight="bold",
                                color=ft.Colors.RED_700, size=12),
                        ft.Text("El siguiente paso te permitirá cobrar o registrar la deuda.",
                                size=11, color=ft.Colors.RED_600),
                    ], spacing=1),
                ], spacing=10),
                bgcolor=ft.Colors.RED_50, padding=10, border_radius=8,
                border=ft.border.all(1, ft.Colors.RED_200),
            )
        elif self._credito > 0.01:
            banner = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.GREEN_700, size=18),
                    ft.Column([
                        ft.Text("El huésped tiene saldo a favor.", weight="bold",
                                color=ft.Colors.GREEN_700, size=12),
                        ft.Text("El siguiente paso te permitirá entregar el vuelto o conservar el crédito.",
                                size=11, color=ft.Colors.GREEN_600),
                    ], spacing=1),
                ], spacing=10),
                bgcolor=ft.Colors.GREEN_50, padding=10, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREEN_200),
            )
        else:
            banner = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700, size=18),
                    ft.Text("Cuenta saldada — no hay deuda ni saldo pendiente.",
                            weight="bold", color=ft.Colors.GREEN_700, size=12),
                ], spacing=10),
                bgcolor=ft.Colors.GREEN_50, padding=10, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREEN_200),
            )

        self._cuerpo.content = ft.Column([
            # Tarjeta huésped
            ft.Container(
                content=ft.Row([
                    ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.PERSON, color=ft.Colors.BLUE_700, size=15),
                            ft.Text(titular.nombre_completo if titular else "N/A",
                                    weight="bold", size=13),
                            ft.Container(
                                content=ft.Text("⚠ VETADO", size=9, color="white",
                                                weight="bold"),
                                bgcolor=ft.Colors.RED_700,
                                padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                border_radius=4,
                                visible=bool(titular and titular.lista_negra),
                            ),
                        ], spacing=5),
                        ft.Text(f"Doc: {titular.documento}" if titular else "",
                                size=11, color=ft.Colors.GREY_600),
                        ft.Text(
                            f"Estadía: {est.entrada.strftime('%d/%m/%Y')} → "
                            f"{est.salida.strftime('%d/%m/%Y')}  ({noches} noche{'s' if noches != 1 else ''})",
                            size=11, color=ft.Colors.GREY_600,
                        ),
                    ], spacing=3),
                ]),
                bgcolor=ft.Colors.BLUE_50, padding=12, border_radius=10,
                border=ft.border.all(1, ft.Colors.BLUE_100),
            ),
            # Chips de balance
            ft.Row([
                chip("Cargos totales", f"${self._total_pend:.2f}",
                     ft.Colors.RED_700 if self._total_pend > 0.01 else ft.Colors.GREY_400,
                     ft.Icons.RECEIPT_LONG),
                chip("Total pagado", f"${total_pagado:.2f}",
                     ft.Colors.GREEN_700, ft.Icons.PAYMENTS),
                chip("Saldo a favor", f"${self._credito:.2f}",
                     ft.Colors.BLUE_700 if self._credito > 0.01 else ft.Colors.GREY_400,
                     ft.Icons.ACCOUNT_BALANCE_WALLET),
            ], spacing=10),
            banner,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    # ════════════════════════════════════════════════════════════════════
    # PASO 1 — BALANCE (deuda o vuelto)
    # ════════════════════════════════════════════════════════════════════

    def _paso_balance(self):
        if self._total_pend > 0.01:
            self._paso_deuda()
        else:
            self._paso_vuelto()

    # ── Deuda ────────────────────────────────────────────────────────────

    def _paso_deuda(self):
        self._titulo.value = "Gestión de Deuda Pendiente"
        self._subtit.value  = (
            f"El huésped debe ${self._total_pend:.2f}  ·  "
            f"Bs. {a_bs(self._total_pend, self._tasa):,.2f}"
        )

        # Widgets de estado de cobro
        self._txt_cobro_estado = ft.Text(
            f"Pendiente: ${self._total_pend:.2f}", weight="bold",
            size=13, color=ft.Colors.RED_700,
        )
        self._col_cobro_pagos = ft.Column(spacing=5)

        # Área de formulario inline — se reemplaza al seleccionar método
        self._area_inline_cobro = ft.Container(
            content=ft.Text("← Selecciona un método de pago",
                            size=12, color=ft.Colors.GREY_500, italic=True),
            padding=ft.padding.symmetric(vertical=8),
        )

        botones = ft.Row(controls=[
            ft.ElevatedButton(
                text=cfg["etiqueta"], icon=cfg["icono"], height=38,
                style=ft.ButtonStyle(
                    color=cfg["color"],
                    bgcolor=ft.Colors.with_opacity(0.07, cfg["color"]),
                    shape=ft.RoundedRectangleBorder(radius=8),
                    side=ft.BorderSide(1.2, ft.Colors.with_opacity(0.3, cfg["color"])),
                ),
                on_click=lambda _, m=metodo: self._inline_cobro(m),
            )
            for metodo, cfg in METODOS.items()
        ], wrap=True, spacing=7, run_spacing=7)

        panel_cobro = ft.Column([
            botones,
            self._area_inline_cobro,
            ft.Divider(height=1),
            self._txt_cobro_estado,
            self._col_cobro_pagos,
        ], spacing=8)

        panel_registrar = ft.Container(
            visible=False,
            content=ft.Column([
                ft.Icon(ft.Icons.PENDING_ACTIONS, size=36, color=ft.Colors.ORANGE_400),
                ft.Text(
                    f"Se registrará una deuda de ${self._total_pend:.2f} en el perfil del huésped.\n"
                    "Si regresa, se le cargará automáticamente en la próxima estadía.",
                    text_align=ft.TextAlign.CENTER, size=12, color=ft.Colors.GREY_700,
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            padding=20, alignment=ft.alignment.center,
        )

        self._panel_cobro_activo    = panel_cobro
        self._panel_registrar_activo = panel_registrar

        self._radio_deuda = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="cobrar",    label="Cobrar la deuda ahora"),
                ft.Radio(value="registrar", label="Registrar como deuda del cliente (para futuras estadías)"),
            ]),
            value="cobrar",
            on_change=self._toggle_modo_deuda,
        )

        self._cuerpo.content = ft.Column([
            ft.Container(
                content=self._radio_deuda,
                bgcolor=ft.Colors.ORANGE_50, padding=10, border_radius=8,
                border=ft.border.all(1, ft.Colors.ORANGE_200),
            ),
            panel_cobro,
            panel_registrar,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    def _inline_cobro(self, metodo):
        """Muestra el formulario de monto INLINE dentro del wizard, sin abrir dialog."""
        cfg   = METODOS[metodo]
        es_bs = cfg["es_bs"]
        restante = self._pend_cobro()
        val_sug  = f"{a_bs(restante, self._tasa):.2f}" if es_bs else f"{restante:.2f}"

        campo_monto = ft.TextField(
            label=f"Monto {'en Bs.' if es_bs else 'en USD'}",
            value=val_sug,
            suffix_text="Bs." if es_bs else "USD",
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True, expand=True,
        )
        necesita_ref = metodo not in [MetodoPago.CASH_USD, MetodoPago.CASH_BS]
        campo_ref = ft.TextField(
            label="Referencia / Nro. confirmación",
            visible=necesita_ref, expand=True,
        )
        error_txt = ft.Text("", color=ft.Colors.RED_700, size=11)

        def confirmar(_):
            try:
                val       = float(campo_monto.value.replace(",", ".") or 0)
                if val <= 0:
                    error_txt.value = "El monto debe ser mayor a 0"
                    self.pagina.update(); return
                monto_usd = round(a_usd(val, self._tasa) if es_bs else val, 2)
                monto_bs  = round(val if es_bs else a_bs(val, self._tasa), 2)
                self._pagos_cobro.append({
                    "metodo": metodo, "monto_usd": monto_usd, "monto_bs": monto_bs,
                    "referencia": campo_ref.value.strip() if necesita_ref else "",
                    "etiqueta": cfg["etiqueta"], "color": cfg["color"], "icono": cfg["icono"],
                    "viz": f"Bs. {val:,.2f}" if es_bs else f"${val:.2f}",
                })
                self._refrescar_estado_cobro()
                # Volver al estado "selecciona método"
                self._area_inline_cobro.content = ft.Text(
                    "← Selecciona otro método o continúa",
                    size=12, color=ft.Colors.GREY_500, italic=True,
                )
                self.pagina.update()
            except ValueError:
                error_txt.value = "Número inválido"
                self.pagina.update()

        def cancelar_form(_):
            self._area_inline_cobro.content = ft.Text(
                "← Selecciona un método de pago",
                size=12, color=ft.Colors.GREY_500, italic=True,
            )
            self.pagina.update()

        self._area_inline_cobro.content = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(cfg["icono"], color=cfg["color"], size=16),
                    ft.Text(cfg["etiqueta"], weight="bold", color=cfg["color"], size=13),
                ], spacing=6),
                ft.Row(
                    [campo_monto, campo_ref] if necesita_ref else [campo_monto],
                    spacing=10,
                ),
                error_txt,
                ft.Row([
                    ft.TextButton("Cancelar", on_click=cancelar_form),
                    ft.ElevatedButton(
                        "+ Agregar pago",
                        bgcolor=cfg["color"], color="white",
                        on_click=confirmar,
                    ),
                ], spacing=10),
            ], spacing=8),
            bgcolor=ft.Colors.with_opacity(0.04, cfg["color"]),
            padding=12, border_radius=10,
            border=ft.border.all(1.5, ft.Colors.with_opacity(0.25, cfg["color"])),
        )
        self.pagina.update()

    def _pend_cobro(self) -> float:
        return round(max(0.0, self._total_pend - sum(p["monto_usd"] for p in self._pagos_cobro)), 2)

    def _refrescar_estado_cobro(self):
        restante = self._pend_cobro()
        self._txt_cobro_estado.value = (
            "✓ Deuda saldada" if restante <= 0.01
            else f"Pendiente: ${restante:.2f}  ·  Bs. {a_bs(restante, self._tasa):,.2f}"
        )
        self._txt_cobro_estado.color = (
            ft.Colors.GREEN_700 if restante <= 0.01 else ft.Colors.RED_700
        )
        self._col_cobro_pagos.controls = [
            ft.Container(
                content=ft.Row([
                    ft.Icon(p["icono"], size=13, color=p["color"]),
                    ft.Text(p["etiqueta"], size=12, expand=True),
                    ft.Text(p["viz"], size=12, weight="bold"),
                    ft.IconButton(
                        ft.Icons.REMOVE_CIRCLE_OUTLINE, icon_size=14,
                        icon_color=ft.Colors.RED_400,
                        on_click=lambda _, i=idx: self._quitar_cobro(i),
                    ),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                bgcolor=ft.Colors.with_opacity(0.06, p["color"]), border_radius=7,
            )
            for idx, p in enumerate(self._pagos_cobro)
        ]

    def _quitar_cobro(self, idx):
        self._pagos_cobro.pop(idx)
        self._refrescar_estado_cobro()
        self.pagina.update()

    def _toggle_modo_deuda(self, _):
        modo = self._radio_deuda.value
        self._panel_cobro_activo.visible     = (modo == "cobrar")
        self._panel_registrar_activo.visible = (modo == "registrar")
        self.pagina.update()

    def _validar_deuda(self) -> bool:
        if not hasattr(self, "_radio_deuda"):
            return True
        if self._radio_deuda.value == "registrar":
            self._decision = "registrar"; return True
        if self._pend_cobro() > 0.01:
            self.pagina.open(ft.SnackBar(
                ft.Text("Aún queda monto por cobrar. Agrega pagos o elige 'Registrar deuda'."),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return False
        self._decision = "cobrar"; return True

    # ── Vuelto ───────────────────────────────────────────────────────────

    def _paso_vuelto(self):
        """
        Paso de gestión de saldo a favor.
        Usa GestorVuelto como componente embebido — sin diálogos anidados.
        """
        self._titulo.value = "Gestión de Saldo a Favor"
        self._subtit.value  = (
            f"El huésped tiene ${self._credito:.2f} a su favor  ·  "
            f"Bs. {a_bs(self._credito, self._tasa):,.2f}"
        )

        # Crear el GestorVuelto una sola vez (preserva valores si se regresa al paso)
        if self._gestor_vuelto is None or abs(self._gestor_vuelto.monto_usd - self._credito) > 0.01:
            self._gestor_vuelto = GestorVuelto(
                monto_usd=self._credito,
                tasa=self._tasa,
                pagina=self.pagina,
            )

        panel_gestor = ft.Column(
            controls=[self._gestor_vuelto.construir()],
            visible=False,
        )

        self._radio_vuelto = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(
                    value="credito",
                    label=f"Conservar ${self._credito:.2f} como crédito para futuras estadías",
                ),
                ft.Radio(value="vuelto", label="Entregar el vuelto ahora"),
            ]),
            value="credito",
            on_change=lambda _: (
                setattr(panel_gestor, "visible", self._radio_vuelto.value == "vuelto"),
                self.pagina.update(),
            ),
        )

        self._cuerpo.content = ft.Column([
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.GREEN_700, size=18),
                    ft.Text(f"Saldo a favor del titular: ${self._credito:.2f}",
                            weight="bold", color=ft.Colors.GREEN_700),
                ], spacing=6),
                bgcolor=ft.Colors.GREEN_50, padding=10, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREEN_200),
            ),
            ft.Container(
                content=self._radio_vuelto,
                bgcolor=ft.Colors.GREY_50, padding=10, border_radius=8,
                border=ft.border.all(1, ft.Colors.GREY_200),
            ),
            panel_gestor,
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

    def _validar_vuelto(self) -> bool:
        if not hasattr(self, "_radio_vuelto"):
            return True
        if self._radio_vuelto.value == "credito":
            self._decision = "credito"; return True
        # Modo vuelto: el GestorVuelto debe cuadrar
        if self._gestor_vuelto is None or not self._gestor_vuelto.es_valido():
            self.pagina.open(ft.SnackBar(
                ft.Text("La distribución del vuelto está incompleta. Verifica que los montos sumen correctamente."),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return False
        self._decision = "vuelto"; return True

    # ════════════════════════════════════════════════════════════════════
    # PASO FINAL — NOTA Y LISTA NEGRA
    # ════════════════════════════════════════════════════════════════════

    def _paso_nota(self):
        self._titulo.value = "Nota de la Estadía"
        self._subtit.value  = "Añade observaciones opcionales antes de cerrar."

        self._campo_nota = ft.TextField(
            label="Nota sobre la estadía (opcional)",
            multiline=True, min_lines=4, max_lines=5,
            hint_text="Comportamiento, preferencias, incidencias...",
            value=self._nota,
            on_change=lambda e: setattr(self, "_nota", e.control.value),
        )
        self._sw_negra = ft.Switch(
            label="Agregar a lista negra",
            value=self._lista_negra,
            active_color=ft.Colors.RED_700,
            on_change=self._toggle_negra,
        )
        self._campo_motivo = ft.TextField(
            label="Motivo del veto",
            hint_text="Describe el motivo...",
            multiline=True, min_lines=2, max_lines=3,
            value=self._motivo_veto,
            visible=self._lista_negra,
            on_change=lambda e: setattr(self, "_motivo_veto", e.control.value),
        )
        self._cuerpo.content = ft.Column([
            self._campo_nota,
            ft.Divider(),
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.BLOCK, color=ft.Colors.RED_700, size=16),
                        ft.Text("Lista Negra", weight="bold", size=13),
                    ], spacing=6),
                    ft.Text(
                        "Activa esta opción si el huésped debe ser vetado. "
                        "El sistema mostrará una advertencia la próxima vez que intente hacer check-in.",
                        size=11, color=ft.Colors.GREY_600,
                    ),
                    self._sw_negra,
                    self._campo_motivo,
                ], spacing=8),
                bgcolor=ft.Colors.RED_50, padding=12, border_radius=10,
                border=ft.border.all(1, ft.Colors.RED_100),
            ),
        ], spacing=12, scroll=ft.ScrollMode.AUTO)

    def _toggle_negra(self, _):
        self._lista_negra = self._sw_negra.value
        self._campo_motivo.visible = self._lista_negra
        self.pagina.update()

    # ════════════════════════════════════════════════════════════════════
    # EJECUCIÓN DEL CHECKOUT
    # ════════════════════════════════════════════════════════════════════

    def _ejecutar(self):
        sesion = SesionLocal()
        try:
            tasa       = self._tasa
            est_bd     = sesion.get(Estadia, self._estadia.id)
            hab_bd     = sesion.get(Habitacion, self.habitacion.id)
            titular_bd = sesion.get(Huesped, self._titular.id) if self._titular else None
            caja       = sesion.query(Caja).first()

            # A. Nota
            if self._nota.strip():
                est_bd.notas = self._nota.strip()

            # B. Lista negra
            if titular_bd and self._lista_negra:
                titular_bd.lista_negra = True
                if self._motivo_veto.strip():
                    titular_bd.motivo_veto = self._motivo_veto.strip()

            # C. Financiero
            if self._total_pend > 0.01:
                if self._decision == "cobrar":
                    for p in self._pagos_cobro:
                        sesion.add(Pago(
                            estadia_id=est_bd.id, monto_usd=p["monto_usd"],
                            monto_bs=p["monto_bs"], tasa_cambio=tasa,
                            metodo=p["metodo"], referencia=p.get("referencia", ""),
                            descripcion="Cobro de deuda en Check-Out",
                            creado_en=datetime.now(), es_devolucion=False,
                        ))
                        if p["metodo"] in [MetodoPago.CASH_USD, MetodoPago.ZELLE, MetodoPago.DEBIT_CARD]:
                            if caja: caja.saldo_principal_usd += p["monto_usd"]
                        else:
                            if caja: caja.saldo_principal_bs  += p["monto_bs"]
                    for l in est_bd.lineas_cuenta:
                        if not l.cancelada:
                            l.cancelada = True
                elif self._decision == "registrar":
                    if titular_bd:
                        titular_bd.credito_usd = (titular_bd.credito_usd or 0.0) - self._total_pend

            elif self._credito > 0.01 and self._decision == "vuelto":
                # Delegar al GestorVuelto reutilizable (valida fondos y registra pagos)
                self._gestor_vuelto.aplicar(sesion, estadia_id=est_bd.id)
                # Limpiar el saldo del titular
                if titular_bd:
                    titular_bd.credito_usd = 0.0
                # Si decision == 'credito': no tocar credito_usd

            # D. Cerrar estadía → habitación a LIMPIEZA
            est_bd.activa  = False
            hab_bd.estado  = EstadoHabitacion.CLEANING
            sesion.commit()

            self.pagina.close(self.dialogo)
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Check-Out Hab. {self.habitacion.numero} — Estado: LIMPIEZA"),
                bgcolor=ft.Colors.GREEN_700, duration=4000,
            ))
            if self.al_completar:
                self.al_completar(self.habitacion)

        except Exception as err:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error en Check-Out: {err}"), bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()