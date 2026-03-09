
import flet as ft
from datetime import datetime
from database.models import Pago, Caja, MetodoPago, Huesped
from utils.calculos_financieros import a_bs, a_usd


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

    def es_valido(self) -> bool:
        diff = abs(self.monto_usd - self.total_configurado_usd())
        return diff < 0.02

    def _validar_en_vivo(self, _):
        total = self.total_configurado_usd()
        diff  = round(self.monto_usd - total, 2)
        if abs(diff) < 0.02:
            self._txt_estado.value = "✓ Distribución correcta"
            self._txt_estado.color = ft.Colors.GREEN_700
        elif diff > 0:
            self._txt_estado.value = f"Falta distribuir: ${diff:.2f}  ·  Bs. {a_bs(diff, self.tasa):,.2f}"
            self._txt_estado.color = ft.Colors.RED_700
        else:
            self._txt_estado.value = f"Excede en ${abs(diff):.2f} — ajusta los montos"
            self._txt_estado.color = ft.Colors.ORANGE_700
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
                    ft.Text(
                        f"Distribución del vuelto: ${self.monto_usd:.2f}  ·  "
                        f"Bs. {a_bs(self.monto_usd, self.tasa):,.2f}",
                        weight="bold", color=ft.Colors.ORANGE_700, size=13,
                    ),
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

    def aplicar(self, sesion, estadia_id: int) -> None:
        """
        Registra los Pago(es_devolucion=True) correspondientes y descuenta
        de las cajas físicas. Debe llamarse dentro de una transacción abierta.
        Lanza Exception si los fondos son insuficientes.
        """
        if not self.es_valido():
            raise Exception(
                f"La distribución del vuelto no cuadra. "
                f"Total configurado: ${self.total_configurado_usd():.2f} "
                f"/ Requerido: ${self.monto_usd:.2f}"
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
                                caja.saldo_principal_usd - v_ppal_usd) if caja else None,
            ),
            (
                v_chica_usd,
                a_bs(v_chica_usd, tasa),
                MetodoPago.CASH_USD,
                "Efectivo USD — Caja Chica",
                lambda: setattr(caja, "caja_chica_usd",
                                caja.caja_chica_usd - v_chica_usd) if caja else None,
            ),
            (
                a_usd(v_ppal_bs, tasa),
                v_ppal_bs,
                MetodoPago.CASH_BS,
                "Efectivo Bs — Caja Principal",
                lambda: setattr(caja, "saldo_principal_bs",
                                caja.saldo_principal_bs - v_ppal_bs) if caja else None,
            ),
            (
                a_usd(v_chica_bs, tasa),
                v_chica_bs,
                MetodoPago.CASH_BS,
                "Efectivo Bs — Caja Chica",
                lambda: setattr(caja, "caja_chica_bs",
                                caja.caja_chica_bs - v_chica_bs) if caja else None,
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

        for monto_usd_f, monto_bs_f, metodo, desc, descontar in fuentes:
            if monto_usd_f < 0.01 and monto_bs_f < 0.01:
                continue  # fuente no utilizada
            descontar()
            sesion.add(Pago(
                estadia_id    = estadia_id,
                monto_usd     = round(monto_usd_f, 2),
                monto_bs      = round(monto_bs_f,  2),
                tasa_cambio   = tasa,
                metodo        = metodo,
                referencia    = desc,
                descripcion   = f"Vuelto — {desc}",
                creado_en     = ahora,
                es_devolucion = True,
            ))

        # ── Registrar saldo a favor si hay diferencia ────────────────────────
        diferencia = self.monto_usd - self.total_configurado_usd()
        if diferencia > 0.02:
            huesped = sesion.query(Huesped).filter_by(estadia_id=estadia_id).first()
            if huesped:
                huesped.acreditar_saldo(diferencia)
                sesion.add(Pago(
                    estadia_id    = estadia_id,
                    monto_usd     = 0.0,
                    monto_bs      = 0.0,
                    tasa_cambio   = self.tasa,
                    metodo        = MetodoPago.SALDO_FAVOR,
                    referencia    = "Saldo a favor",
                    descripcion   = f"Saldo a favor acreditado: ${diferencia:.2f}",
                    creado_en     = ahora,
                    es_devolucion = True,
                ))