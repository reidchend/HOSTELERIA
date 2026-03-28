# modules/finance/gestor_vuelto.py
#
# Componente reutilizable para gestionar la entrega de vueltos / devoluciones.
#
# LÓGICA FLEXIBLE:
#   El recepcionista puede entregar UNA PARTE del vuelto (lo que tenga en caja).
#   El remanente (monto_usd - total_entregado) queda automáticamente como
#   saldo a favor (crédito) en el perfil del huésped titular.
#
# FUENTES DE VUELTO:
#   Cajas físicas  → Caja Principal USD  /  Caja Chica USD
#                    Caja Principal Bs   /  Caja Chica Bs
#   Administración → Pago Móvil (electrónico, sin salida de caja física)
#                    Transferencia Bs    (electrónico, sin salida de caja física)
#
# USO:
#   gestor = GestorVuelto(monto_usd=15.00, tasa=36.5, pagina=pagina)
#   widget = gestor.construir()   # ft.Container listo para embeber inline
#
#   # antes del commit (siempre válido — puede entregar $0 y todo queda como crédito):
#   credito_generado = gestor.aplicar(sesion, estadia_id=estadia.id, titular_id=huesped.id)

import flet as ft
from datetime import datetime
from database.models import Pago, Caja, MetodoPago, Huesped
from utils.calculos_financieros import a_bs, a_usd
from modules.finance.engine import ledger as led


class GestorVuelto:
    """
    Widget inline que gestiona el desglose de un vuelto entre múltiples fuentes.
    No abre ningún diálogo secundario — todo es inline para compatibilidad Flet 0.28.3.
    """

    def __init__(self, monto_usd: float, tasa: float, pagina: ft.Page):
        self.monto_usd = round(monto_usd, 2)
        self.tasa      = tasa
        self.pagina    = pagina

        # ── Campos de cajas físicas ──────────────────────────────────────
        self._f_ppal_usd  = ft.TextField(
            label="Caja Principal $",
            value=f"{monto_usd:.2f}",
            suffix_text="USD", width=148,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
        )
        self._f_chica_usd = ft.TextField(
            label="Caja Chica $",
            value="0.00",
            suffix_text="USD", width=148,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
        )
        self._f_ppal_bs   = ft.TextField(
            label="Caja Principal Bs",
            value="0.00",
            suffix_text="Bs.", width=148,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
        )
        self._f_chica_bs  = ft.TextField(
            label="Caja Chica Bs",
            value="0.00",
            suffix_text="Bs.", width=148,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
        )

        # ── Campos de admin (electrónico) ────────────────────────────────
        self._f_pm_bs    = ft.TextField(
            label="Pago Móvil Bs",
            value="0.00",
            suffix_text="Bs.", width=148,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
        )
        self._f_pm_ref   = ft.TextField(
            label="Referencia Pago Móvil",
            width=200,
            hint_text="Nro. confirmación",
        )
        self._f_transf_bs  = ft.TextField(
            label="Transferencia Bs",
            value="0.00",
            suffix_text="Bs.", width=148,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.RIGHT,
        )
        self._f_transf_ref = ft.TextField(
            label="Referencia Transferencia",
            width=200,
            hint_text="Nro. confirmación",
        )

        # ── Indicador de estado ──────────────────────────────────────────
        self._txt_estado = ft.Text("", size=12, weight="bold")

        # Conectar validación en tiempo real
        for campo in [
            self._f_ppal_usd, self._f_chica_usd,
            self._f_ppal_bs,  self._f_chica_bs,
            self._f_pm_bs,    self._f_transf_bs,
        ]:
            campo.on_change = self._validar_en_vivo

        self._validar_en_vivo(None)

    # ════════════════════════════════════════════════════════════════════
    # LÓGICA DE CÁLCULO
    # ════════════════════════════════════════════════════════════════════

    def _leer(self, campo: ft.TextField) -> float:
        """Lee el valor de un TextField, devuelve 0.0 si está vacío o es inválido."""
        try:
            return max(0.0, float((campo.value or "0").replace(",", ".")))
        except ValueError:
            return 0.0

    def total_configurado_usd(self) -> float:
        """Suma todas las fuentes convertidas a USD."""
        usd_fisico  = self._leer(self._f_ppal_usd) + self._leer(self._f_chica_usd)
        bs_fisico   = self._leer(self._f_ppal_bs)  + self._leer(self._f_chica_bs)
        bs_admin    = self._leer(self._f_pm_bs)    + self._leer(self._f_transf_bs)
        return round(usd_fisico + a_usd(bs_fisico + bs_admin, self.tasa), 2)

    def credito_remanente(self) -> float:
        """Monto que NO se entrega físicamente y queda como crédito al huésped."""
        return round(max(0.0, self.monto_usd - self.total_configurado_usd()), 2)

    def es_valido(self) -> bool:
        """
        Siempre True mientras el total entregado no EXCEDA el monto a devolver.
        El recepcionista puede entregar menos — el remanente va a crédito.
        """
        return self.total_configurado_usd() <= self.monto_usd + 0.02

    def _validar_en_vivo(self, _):
        total     = self.total_configurado_usd()
        remanente = round(self.monto_usd - total, 2)
        if total > self.monto_usd + 0.02:
            # Único caso inválido: el recepcionista puso más de lo que debe devolver
            self._txt_estado.value = f"⚠ Excede en ${total - self.monto_usd:.2f} — reduce los montos"
            self._txt_estado.color = ft.Colors.RED_700
        elif remanente < 0.02:
            self._txt_estado.value = "✓ Vuelto completo — se entrega todo en efectivo/transferencia"
            self._txt_estado.color = ft.Colors.GREEN_700
        else:
            self._txt_estado.value = (
                f"ℹ ${remanente:.2f} quedará como saldo a favor del huésped  "
"                "f"·  Bs. {a_bs(remanente, self.tasa):,.2f}"
            )
            self._txt_estado.color = ft.Colors.BLUE_700
        try:
            self._txt_estado.update()
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN DEL WIDGET
    # ════════════════════════════════════════════════════════════════════

    def construir(self) -> ft.Container:
        """Devuelve el widget listo para embeberlo inline en cualquier diálogo."""

        def seccion(titulo, icono, color, controles):
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(icono, size=14, color=color),
                        ft.Text(titulo, size=11, weight="bold",
                                color=color),
                    ], spacing=5),
                    ft.Row(controls=controles, spacing=8, wrap=True),
                ], spacing=6),
                bgcolor=ft.Colors.with_opacity(0.04, color),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                border_radius=8,
                border=ft.border.all(1, ft.Colors.with_opacity(0.15, color)),
            )

        return ft.Container(
            content=ft.Column([
                # Encabezado
                ft.Row([
                    ft.Icon(ft.Icons.CURRENCY_EXCHANGE, color=ft.Colors.ORANGE_700, size=16),
                    ft.Column([
                        ft.Text(
                            f"Vuelto a gestionar: ${self.monto_usd:.2f}  ·  "
"                            "f"Bs. {a_bs(self.monto_usd, self.tasa):,.2f}",
                            weight="bold", color=ft.Colors.ORANGE_700, size=13,
                        ),
                        ft.Text(
                            "Puedes entregar menos — el resto queda como crédito al huésped.",
                            size=10, color=ft.Colors.ORANGE_400, italic=True,
                        ),
                    ], spacing=2),
                ], spacing=6),

                # Sección cajas físicas
                seccion(
                    "CAJAS FÍSICAS — Efectivo",
                    ft.Icons.ACCOUNT_BALANCE,
                    ft.Colors.BLUE_800,
                    [
                        self._f_ppal_usd,
                        self._f_chica_usd,
                        self._f_ppal_bs,
                        self._f_chica_bs,
                    ],
                ),

                # Sección administración (electrónico)
                seccion(
                    "VÍA ADMINISTRACIÓN — Electrónico",
                    ft.Icons.ADMIN_PANEL_SETTINGS,
                    ft.Colors.PURPLE_700,
                    [
                        self._f_pm_bs,
                        self._f_pm_ref,
                        self._f_transf_bs,
                        self._f_transf_ref,
                    ],
                ),

                # Indicador de estado
                ft.Container(
                    content=self._txt_estado,
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    bgcolor=ft.Colors.GREY_50,
                    border_radius=6,
                    border=ft.border.all(1, ft.Colors.GREY_200),
                ),
            ], spacing=10),
            bgcolor=ft.Colors.ORANGE_50,
            padding=14,
            border_radius=10,
            border=ft.border.all(1, ft.Colors.ORANGE_200),
        )

    # ════════════════════════════════════════════════════════════════════
    # APLICACIÓN EN BASE DE DATOS
    # ════════════════════════════════════════════════════════════════════

    def aplicar(self, sesion, estadia_id: int, titular_id: int = None) -> float:
        """
        Registra los vueltos físicos/electrónicos configurados y descuenta
        de las cajas. El remanente (monto no entregado) se acredita en
        Huesped.credito_usd del titular si se proporciona titular_id.

        Devuelve el monto acreditado como crédito (0.0 si se entregó todo).
        Lanza Exception si los fondos son insuficientes o si se excede el monto.
        """
        if not self.es_valido():
            raise Exception(
                f"El total a entregar (${self.total_configurado_usd():.2f}) excede "
"                "f"el vuelto disponible (${self.monto_usd:.2f}). Ajusta los montos."
            )

        caja  = sesion.query(Caja).first()
        tasa  = self.tasa
        ahora = datetime.now()

        # ── Valores leídos ───────────────────────────────────────────────
        v_ppal_usd   = self._leer(self._f_ppal_usd)
        v_chica_usd  = self._leer(self._f_chica_usd)
        v_ppal_bs    = self._leer(self._f_ppal_bs)
        v_chica_bs   = self._leer(self._f_chica_bs)
        v_pm_bs      = self._leer(self._f_pm_bs)
        v_transf_bs  = self._leer(self._f_transf_bs)

        ref_pm    = self._f_pm_ref.value.strip()    or "—"
        ref_transf= self._f_transf_ref.value.strip() or "—"

        # ── Validar fondos disponibles ───────────────────────────────────
        if caja:
            if caja.saldo_principal_usd < v_ppal_usd:
                raise Exception(
                    f"Caja Principal no tiene fondos suficientes en USD. "
                    f"Disponible: ${caja.saldo_principal_usd:.2f}"
                )
            if caja.caja_chica_usd < v_chica_usd:
                raise Exception(
                    f"Caja Chica no tiene fondos suficientes en USD. "
                    f"Disponible: ${caja.caja_chica_usd:.2f}"
                )
            if caja.saldo_principal_bs < v_ppal_bs:
                raise Exception(
                    f"Caja Principal no tiene fondos suficientes en Bs. "
                    f"Disponible: Bs. {caja.saldo_principal_bs:,.2f}"
                )
            if caja.caja_chica_bs < v_chica_bs:
                raise Exception(
                    f"Caja Chica no tiene fondos suficientes en Bs. "
                    f"Disponible: Bs. {caja.caja_chica_bs:,.2f}"
                )

        # ── Registrar Pago y descontar por fuente ────────────────────────
        # Cada fuente con monto > 0 genera su propio registro de Pago.
        # Esto permite un historial detallado de dónde salió cada vuelto.

        fuentes = [
            # (monto_usd, monto_bs, metodo, referencia, descuenta_campo_caja)
            (
                v_ppal_usd,
                a_bs(v_ppal_usd, tasa),
                MetodoPago.CASH_USD,
                "Efectivo USD — Caja Principal",
                lambda: setattr(caja, "saldo_principal_usd",
                                __import__("decimal").Decimal(str(caja.saldo_principal_usd or 0)) - __import__("decimal").Decimal(str(v_ppal_usd))) if caja else None,
            ),
            (
                v_chica_usd,
                a_bs(v_chica_usd, tasa),
                MetodoPago.CASH_USD,
                "Efectivo USD — Caja Chica",
                lambda: setattr(caja, "caja_chica_usd",
                                __import__("decimal").Decimal(str(caja.caja_chica_usd or 0)) - __import__("decimal").Decimal(str(v_chica_usd))) if caja else None,
            ),
            (
                a_usd(v_ppal_bs, tasa),
                v_ppal_bs,
                MetodoPago.CASH_BS,
                "Efectivo Bs — Caja Principal",
                lambda: setattr(caja, "saldo_principal_bs",
                                __import__("decimal").Decimal(str(caja.saldo_principal_bs or 0)) - __import__("decimal").Decimal(str(v_ppal_bs))) if caja else None,
            ),
            (
                a_usd(v_chica_bs, tasa),
                v_chica_bs,
                MetodoPago.CASH_BS,
                "Efectivo Bs — Caja Chica",
                lambda: setattr(caja, "caja_chica_bs",
                                __import__("decimal").Decimal(str(caja.caja_chica_bs or 0)) - __import__("decimal").Decimal(str(v_chica_bs))) if caja else None,
            ),
            (
                a_usd(v_pm_bs, tasa),
                v_pm_bs,
                MetodoPago.PAGO_MOVIL,
                f"Pago Móvil Admin — Ref: {ref_pm}",
                lambda: None,   # sin salida de caja física
            ),
            (
                a_usd(v_transf_bs, tasa),
                v_transf_bs,
                MetodoPago.TRANSFER_BS,
                f"Transferencia Admin — Ref: {ref_transf}",
                lambda: None,   # sin salida de caja física
            ),
        ]

        from decimal import Decimal as _D
        for monto_usd_f, monto_bs_f, metodo, desc, descontar in fuentes:
            if monto_usd_f < 0.01 and monto_bs_f < 0.01:
                continue  # fuente no utilizada
            descontar()
            nuevo_pago = Pago(
                estadia_id    = estadia_id,
                monto_usd     = round(monto_usd_f, 2),
                monto_bs      = round(monto_bs_f,  2),
                tasa_cambio   = tasa,
                metodo        = metodo,
                referencia    = desc,
                descripcion   = f"Vuelto — {desc}",
                creado_en     = ahora,
                es_devolucion = True,
            )
            sesion.add(nuevo_pago)
            sesion.flush()
            led.registrar_devolucion(
                sesion,
                estadia_id = estadia_id,
                concepto   = f"Vuelto — {desc}",
                monto_usd  = _D(str(round(monto_usd_f, 4))),
                tasa       = _D(str(tasa)),
                referencia = desc,
                pago_id    = nuevo_pago.id,
            )

        # ── Remanente → crédito al huésped titular ───────────────────────
        remanente = self.credito_remanente()
        if remanente > 0.01 and titular_id:
            titular = sesion.get(Huesped, titular_id)
            if titular:
                titular.credito_usd = (
                    _D(str(titular.credito_usd or 0)) + _D(str(remanente))
                )
                titular.credito_origen = "vuelto"
                # Asentar en ledger como devolución pendiente (crédito)
                led.registrar_devolucion(
                    sesion,
                    estadia_id = estadia_id,
                    concepto   = f"Vuelto a favor — ${remanente:.2f} acreditados al huésped",
                    monto_usd  = _D(str(remanente)),
                    tasa       = _D(str(tasa)),
                    referencia = "Vuelto a favor",
                )

        return remanente