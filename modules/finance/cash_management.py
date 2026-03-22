# modules/finance/cash_management.py

import flet as ft
from datetime import datetime, date
from decimal import Decimal
from database.connection import SesionLocal
from database.models import (
    Caja, Configuracion, Pago, MetodoPago,
    Habitacion, EstadoHabitacion, FolioLinea, TipoHabitacion,
)
from utils.calculos_financieros import a_bs


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _f(val) -> float:
    """Convierte Decimal/None a float seguro."""
    try:
        return float(val or 0)
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# PANTALLA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class PantallaGestionCaja(ft.Container):
    """
    Vista de administración con dos pestañas:

    TAB 1 — FINANZAS DEL DÍA
      · Saldos en tiempo real de las cuatro cajas (Principal $, Principal Bs,
        Chica $, Chica Bs).
      · Lo facturado hoy desglosado por método de pago.
      · Ingresos por tipo: efectivo, banco (Zelle/Transferencia/Débito),
        pago móvil.
      · Movimientos manuales de caja chica.
      · Actualización de tasa de cambio.

    TAB 2 — CONFIGURACIÓN DE HABITACIONES
      · Lista editable de habitaciones: tipo, precio base, precio actual,
        capacidad, descripción.
    """

    # Los tipos se cargan dinámicamente desde TipoHabitacion en la BD

    def __init__(self, pagina: ft.Page, estado_app: dict):
        super().__init__()
        self.pagina     = pagina
        self.estado_app = estado_app
        self.expand     = True
        self.padding    = ft.padding.symmetric(horizontal=32, vertical=24)
        self._construir()

    # ─────────────────────────────────────────────────────────────────────────
    # DATOS
    # ─────────────────────────────────────────────────────────────────────────

    def _cargar_datos(self) -> dict:
        sesion = SesionLocal()
        try:
            caja = sesion.query(Caja).first()
            tasa_cfg = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            tasa = float(tasa_cfg.valor) if tasa_cfg else 1.0

            # Inicio del día actual
            hoy_inicio = datetime.combine(date.today(), datetime.min.time())

            # Todos los pagos de hoy (cobros + devoluciones)
            pagos_hoy = sesion.query(Pago).filter(
                Pago.creado_en >= hoy_inicio,
            ).all()

            cobros   = [p for p in pagos_hoy if not p.es_devolucion]
            vueltos  = [p for p in pagos_hoy if p.es_devolucion]

            # Facturado hoy (folio_lines creadas hoy)
            folio_hoy = sesion.query(FolioLinea).filter(
                FolioLinea.creado_en >= hoy_inicio,
            ).all()
            facturado_hoy = sum(_f(l.total_usd) for l in folio_hoy)

            # Desglose de cobros por método
            def _suma(metodos, campo="monto_usd"):
                return sum(
                    _f(getattr(p, campo))
                    for p in cobros
                    if p.metodo in metodos
                )

            efectivo_usd  = _suma([MetodoPago.CASH_USD])
            efectivo_bs   = _suma([MetodoPago.CASH_BS], "monto_bs")
            banco_usd     = _suma([MetodoPago.ZELLE, MetodoPago.DEBIT_CARD])
            banco_bs      = _suma([MetodoPago.TRANSFER_BS], "monto_bs")
            pago_movil_bs = _suma([MetodoPago.PAGO_MOVIL], "monto_bs")

            total_cobrado_usd = sum(_f(p.monto_usd) for p in cobros)
            total_vuelto_usd  = sum(_f(p.monto_usd) for p in vueltos)

            return {
                "tasa":            tasa,
                "tasa_valor":      tasa_cfg.valor if tasa_cfg else "1.0",
                "ppal_usd":        _f(caja.saldo_principal_usd) if caja else 0.0,
                "ppal_bs":         _f(caja.saldo_principal_bs)  if caja else 0.0,
                "chica_usd":       _f(caja.caja_chica_usd)      if caja else 0.0,
                "chica_bs":        _f(caja.caja_chica_bs)       if caja else 0.0,
                "facturado_hoy":   facturado_hoy,
                "cobrado_hoy":     total_cobrado_usd,
                "vueltos_hoy":     total_vuelto_usd,
                "efectivo_usd":    efectivo_usd,
                "efectivo_bs":     efectivo_bs,
                "banco_usd":       banco_usd,
                "banco_bs":        banco_bs,
                "pago_movil_bs":   pago_movil_bs,
            }
        except Exception as e:
            print(f"❌ Error cargando datos caja: {e}")
            return {}
        finally:
            sesion.close()

    def _cargar_habitaciones(self) -> list:
        sesion = SesionLocal()
        try:
            from sqlalchemy import cast, Integer
            return (
                sesion.query(Habitacion)
                .order_by(cast(Habitacion.numero, Integer))
                .all()
            )
        finally:
            sesion.close()

    def _cargar_tipos(self) -> list:
        """Devuelve los TipoHabitacion ordenados por nombre.
        Si no hay ninguno crea los tipos por defecto."""
        sesion = SesionLocal()
        try:
            tipos = sesion.query(TipoHabitacion).order_by(TipoHabitacion.nombre).all()
            if not tipos:
                defaults = [
                    ("Estándar",    50.0,  50.0, 2),
                    ("Doble",       75.0,  75.0, 2),
                    ("Suite",      120.0, 120.0, 2),
                    ("Familiar",    90.0,  90.0, 4),
                    ("VIP",        150.0, 150.0, 2),
                    ("Presidencial",200.0,200.0, 2),
                ]
                for nombre, pb, pa, cap in defaults:
                    sesion.add(TipoHabitacion(
                        nombre=nombre,
                        precio_base_usd=Decimal(str(pb)),
                        precio_actual_usd=Decimal(str(pa)),
                        capacidad_default=cap,
                    ))
                sesion.commit()
                tipos = sesion.query(TipoHabitacion).order_by(TipoHabitacion.nombre).all()
            return tipos
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN UI
    # ─────────────────────────────────────────────────────────────────────────

    # PATCH para modules/finance/cash_management.py
# Reemplazar el método _construir() existente con este.
# El único cambio es agregar el tercer Tab de Telegram.

    def _construir(self):
        datos = self._cargar_datos()
        if not datos:
            self.content = ft.Text("No se pudo cargar la información financiera.")
            return

        self._campo_tasa = ft.TextField(
            value=datos["tasa_valor"],
            suffix_text="Bs/USD",
            text_align=ft.TextAlign.RIGHT,
            width=160,
            dense=True,
            border_color=ft.Colors.BLUE_300,
        )

        # ── Tab de Telegram (nuevo) ───────────────────────────────────────────
        from modules.notifications.panel_config import construir_panel_telegram
        tab_telegram = ft.Tab(
            text="Telegram",
            icon=ft.Icons.SEND,
            content=ft.Container(
                content=construir_panel_telegram(self.pagina),
                padding=ft.padding.only(top=20),
            ),
        )

        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            tab_alignment=ft.TabAlignment.START,
            tabs=[
                ft.Tab(
                    text="Finanzas del Día",
                    icon=ft.Icons.BAR_CHART,
                    content=ft.Container(
                        content=self._tab_finanzas(datos),
                        padding=ft.padding.only(top=20),
                    ),
                ),
                ft.Tab(
                    text="Habitaciones",
                    icon=ft.Icons.BED,
                    content=ft.Container(
                        content=self._tab_habitaciones(),
                        padding=ft.padding.only(top=20),
                    ),
                ),
                tab_telegram,   # ← NUEVO
            ],
            expand=True,
        )

        self.content = ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("Panel de Administración",
                            size=26, weight="bold", color=ft.Colors.BLUE_GREY_900),
                    ft.Text("Finanzas en tiempo real · Configuración del hotel",
                            size=13, color=ft.Colors.GREY_600),
                ], spacing=2, expand=True),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CURRENCY_EXCHANGE,
                                color=ft.Colors.BLUE_700, size=16),
                        ft.Text("Tasa:", size=12, color=ft.Colors.GREY_700),
                        self._campo_tasa,
                        ft.IconButton(
                            ft.Icons.CHECK_CIRCLE,
                            icon_color=ft.Colors.BLUE_700,
                            tooltip="Actualizar tasa",
                            on_click=lambda _: self._actualizar_tasa(),
                        ),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor=ft.Colors.BLUE_50,
                    padding=ft.padding.symmetric(horizontal=14, vertical=8),
                    border_radius=10,
                    border=ft.border.all(1, ft.Colors.BLUE_200),
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),

            ft.Divider(height=1, color=ft.Colors.GREY_200),
            tabs,
        ], spacing=16, expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 — FINANZAS
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_finanzas(self, d: dict) -> ft.Control:
        tasa = d.get("tasa", 1.0)

        def tarjeta_caja(titulo, valor_usd, valor_bs, color, icono, subtitulo=""):
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(icono, color=ft.Colors.WHITE, size=18),
                            bgcolor=color,
                            border_radius=8, width=34, height=34,
                            alignment=ft.alignment.center,
                        ),
                        ft.Column([
                            ft.Text(titulo, size=11, color=ft.Colors.GREY_600,
                                    weight="bold"),
                            ft.Text(subtitulo, size=9, color=ft.Colors.GREY_400,
                                    italic=True) if subtitulo else ft.Container(height=0),
                        ], spacing=0),
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(height=8),
                    ft.Text(f"${valor_usd:,.2f}",
                            size=22, weight="bold", color=color),
                    ft.Text(f"Bs. {valor_bs:,.2f}",
                            size=11, color=ft.Colors.GREY_500),
                ], spacing=4),
                width=210, height=130,
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1.5, ft.Colors.with_opacity(0.3, color)),
                border_radius=12,
                padding=16,
                shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.BLACK12,
                                    offset=ft.Offset(0, 3)),
            )

        def tarjeta_metodo(label, valor_usd=None, valor_bs=None,
                           color=ft.Colors.GREY_700, icono=ft.Icons.PAID):
            lineas = []
            if valor_usd is not None:
                lineas.append(ft.Text(f"${valor_usd:,.2f}", size=16,
                                      weight="bold", color=color))
            if valor_bs is not None:
                lineas.append(ft.Text(f"Bs. {valor_bs:,.2f}", size=11,
                                      color=ft.Colors.GREY_500))
            return ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(icono, color=ft.Colors.WHITE, size=14),
                        bgcolor=color, border_radius=6, width=26, height=26,
                        alignment=ft.alignment.center,
                    ),
                    ft.Column([
                        ft.Text(label, size=10, color=ft.Colors.GREY_600,
                                weight="bold"),
                        *lineas,
                    ], spacing=1, expand=True),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.GREY_50,
                border=ft.border.all(1, ft.Colors.GREY_200),
                border_radius=8, padding=12, width=170,
            )

        # Fila de cajas
        fila_cajas = ft.Row([
            tarjeta_caja("Caja Principal $",
                         d["ppal_usd"], a_bs(d["ppal_usd"], tasa),
                         ft.Colors.GREEN_700, ft.Icons.ACCOUNT_BALANCE,
                         "Ventas del turno"),
            tarjeta_caja("Caja Principal Bs",
                         d["ppal_bs"] / tasa if tasa else 0, d["ppal_bs"],
                         ft.Colors.TEAL_700, ft.Icons.MONEY,
                         "Ventas en bolívares"),
            tarjeta_caja("Caja Chica $",
                         d["chica_usd"], a_bs(d["chica_usd"], tasa),
                         ft.Colors.BLUE_700, ft.Icons.ACCOUNT_BALANCE_WALLET,
                         "Fondo para vueltos"),
            tarjeta_caja("Caja Chica Bs",
                         d["chica_bs"] / tasa if tasa else 0, d["chica_bs"],
                         ft.Colors.INDIGO_700, ft.Icons.WALLET,
                         "Fondo en bolívares"),
        ], spacing=14, wrap=True)

        # Resumen del día
        neto = d["cobrado_hoy"] - d["vueltos_hoy"]
        resumen_dia = ft.Container(
            content=ft.Column([
                ft.Text("RESUMEN DEL DÍA", size=10, weight="bold",
                        color=ft.Colors.GREY_500),
                ft.Row([
                    ft.Column([
                        ft.Text(f"${d['facturado_hoy']:,.2f}", size=26,
                                weight="bold", color=ft.Colors.BLUE_900),
                        ft.Text("Facturado", size=11, color=ft.Colors.GREY_500),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.VerticalDivider(width=1, color=ft.Colors.GREY_300),
                    ft.Column([
                        ft.Text(f"${d['cobrado_hoy']:,.2f}", size=26,
                                weight="bold", color=ft.Colors.GREEN_700),
                        ft.Text("Cobrado", size=11, color=ft.Colors.GREY_500),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.VerticalDivider(width=1, color=ft.Colors.GREY_300),
                    ft.Column([
                        ft.Text(f"${d['vueltos_hoy']:,.2f}", size=26,
                                weight="bold", color=ft.Colors.ORANGE_700),
                        ft.Text("Vueltos", size=11, color=ft.Colors.GREY_500),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.VerticalDivider(width=1, color=ft.Colors.GREY_300),
                    ft.Column([
                        ft.Text(f"${neto:,.2f}", size=26,
                                weight="bold",
                                color=ft.Colors.GREEN_800 if neto >= 0
                                      else ft.Colors.RED_700),
                        ft.Text("Neto ingresado", size=11, color=ft.Colors.GREY_500),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                ], spacing=28, alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=ft.Colors.WHITE,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=12,
            padding=ft.padding.symmetric(horizontal=24, vertical=18),
            shadow=ft.BoxShadow(blur_radius=6, color=ft.Colors.BLACK12,
                                offset=ft.Offset(0, 2)),
        )

        # Desglose por método de pago
        desglose = ft.Column([
            ft.Text("Desglose por método de pago", size=11, weight="bold",
                    color=ft.Colors.GREY_600),
            ft.Row([
                tarjeta_metodo("Efectivo $", valor_usd=d["efectivo_usd"],
                               color=ft.Colors.GREEN_700,
                               icono=ft.Icons.ATTACH_MONEY),
                tarjeta_metodo("Efectivo Bs",
                               valor_usd=d["efectivo_bs"] / tasa if tasa else 0,
                               valor_bs=d["efectivo_bs"],
                               color=ft.Colors.TEAL_700,
                               icono=ft.Icons.MONEY),
                tarjeta_metodo("Zelle / Débito", valor_usd=d["banco_usd"],
                               color=ft.Colors.INDIGO_700,
                               icono=ft.Icons.SEND),
                tarjeta_metodo("Transferencia",
                               valor_usd=d["banco_bs"] / tasa if tasa else 0,
                               valor_bs=d["banco_bs"],
                               color=ft.Colors.BLUE_700,
                               icono=ft.Icons.SWAP_HORIZ),
                tarjeta_metodo("Pago Móvil",
                               valor_usd=d["pago_movil_bs"] / tasa if tasa else 0,
                               valor_bs=d["pago_movil_bs"],
                               color=ft.Colors.PURPLE_700,
                               icono=ft.Icons.PHONE_ANDROID),
            ], spacing=10, wrap=True),
        ], spacing=8)

        # Operaciones manuales caja chica
        ops_caja = ft.Container(
            content=ft.Column([
                ft.Text("OPERACIONES MANUALES — CAJA CHICA", size=10,
                        weight="bold", color=ft.Colors.GREY_500),
                ft.Row([
                    ft.ElevatedButton(
                        "Ingreso Manual",
                        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                        bgcolor=ft.Colors.GREEN_50, color=ft.Colors.GREEN_800,
                        style=ft.ButtonStyle(
                            side=ft.BorderSide(1.5, ft.Colors.GREEN_300),
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                        on_click=lambda _: self._dlg_movimiento(es_ingreso=True),
                    ),
                    ft.ElevatedButton(
                        "Egreso / Gasto",
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        bgcolor=ft.Colors.RED_50, color=ft.Colors.RED_800,
                        style=ft.ButtonStyle(
                            side=ft.BorderSide(1.5, ft.Colors.RED_300),
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                        on_click=lambda _: self._dlg_movimiento(es_ingreso=False),
                    ),
                    ft.ElevatedButton(
                        "Refrescar datos",
                        icon=ft.Icons.REFRESH,
                        bgcolor=ft.Colors.BLUE_50, color=ft.Colors.BLUE_800,
                        style=ft.ButtonStyle(
                            side=ft.BorderSide(1.5, ft.Colors.BLUE_300),
                            shape=ft.RoundedRectangleBorder(radius=8),
                        ),
                        on_click=lambda _: self._refrescar(),
                    ),
                ], spacing=12),
            ], spacing=10),
            bgcolor=ft.Colors.GREY_50,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=10,
            padding=16,
        )

        return ft.Column([
            fila_cajas,
            resumen_dia,
            desglose,
            ops_caja,
        ], spacing=20, scroll=ft.ScrollMode.AUTO, expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 — HABITACIONES
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_habitaciones(self) -> ft.Control:
        """
        Dos paneles lado a lado:
          Izquierdo  — Tipos de habitación con sus precios (editable, guardado masivo).
          Derecho    — Habitaciones: solo se asigna el tipo; el precio viene del tipo.
        """
        tipos        = self._cargar_tipos()
        habitaciones = self._cargar_habitaciones()

        # ── Mapa tipo→precio para mostrar en las filas de habitaciones ──────
        precio_por_tipo = {t.nombre: _f(t.precio_actual_usd) for t in tipos}

        # ════════════════════════════════════════════════════════════════════
        # PANEL IZQUIERDO — tipos con sus precios
        # ════════════════════════════════════════════════════════════════════

        # Campos editables de tipos {tipo_id: {campo: TextField}}
        campos_tipos: dict = {}

        def fila_tipo(tipo: TipoHabitacion) -> ft.Container:
            tf_pb  = ft.TextField(
                value=f"{_f(tipo.precio_base_usd):.2f}",
                prefix_text="$", width=90, dense=True,
                keyboard_type=ft.KeyboardType.NUMBER,
                text_align=ft.TextAlign.RIGHT,
            )
            tf_pa  = ft.TextField(
                value=f"{_f(tipo.precio_actual_usd):.2f}",
                prefix_text="$", width=90, dense=True,
                keyboard_type=ft.KeyboardType.NUMBER,
                text_align=ft.TextAlign.RIGHT,
            )
            tf_cap = ft.TextField(
                value=str(tipo.capacidad_default or 2),
                width=50, dense=True,
                keyboard_type=ft.KeyboardType.NUMBER,
                text_align=ft.TextAlign.CENTER,
            )
            campos_tipos[tipo.id] = {
                "nombre": tipo.nombre,
                "pb": tf_pb, "pa": tf_pa, "cap": tf_cap,
            }
            return ft.Container(
                content=ft.Row([
                    ft.Text(tipo.nombre, size=12, weight="bold",
                            color=ft.Colors.BLUE_GREY_800, expand=True),
                    tf_pb,
                    tf_pa,
                    tf_cap,
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1, ft.Colors.GREY_200),
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=10, vertical=8),
                margin=ft.margin.only(bottom=4),
            )

        def guardar_tipos(_):
            sesion = SesionLocal()
            try:
                for tid, campos in campos_tipos.items():
                    t = sesion.get(TipoHabitacion, tid)
                    if not t:
                        continue
                    t.precio_base_usd   = Decimal(campos["pb"].value.replace(",",".") or "0")
                    t.precio_actual_usd = Decimal(campos["pa"].value.replace(",",".") or "0")
                    t.capacidad_default = int(campos["cap"].value or 2)
                    # Actualizar todas las habitaciones de este tipo
                    habs = sesion.query(Habitacion).filter(
                        Habitacion.tipo == t.nombre
                    ).all()
                    for h in habs:
                        h.precio_base_usd   = t.precio_base_usd
                        h.precio_actual_usd = t.precio_actual_usd
                        h.capacidad_maxima  = t.capacidad_default
                sesion.commit()
                self.pagina.open(ft.SnackBar(
                    ft.Text("Tipos y precios actualizados en todas las habitaciones"),
                    bgcolor=ft.Colors.GREEN_700,
                ))
                self._refrescar()
            except Exception as err:
                sesion.rollback()
                self.pagina.open(ft.SnackBar(
                    ft.Text(f"Error: {err}"), bgcolor=ft.Colors.RED_700,
                ))
            finally:
                sesion.close()

        header_tipos = ft.Container(
            content=ft.Row([
                ft.Text("Tipo", size=10, weight="bold",
                        color=ft.Colors.GREY_500, expand=True),
                ft.Text("P. Base", size=10, weight="bold",
                        color=ft.Colors.GREY_500, width=90),
                ft.Text("P. Actual", size=10, weight="bold",
                        color=ft.Colors.GREY_500, width=90),
                ft.Text("Cap.", size=10, weight="bold",
                        color=ft.Colors.GREY_500, width=50),
            ], spacing=8),
            bgcolor=ft.Colors.GREY_50,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=ft.border_radius.only(top_left=8, top_right=8),
            border=ft.border.all(1, ft.Colors.GREY_200),
        )

        panel_tipos = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CATEGORY, color=ft.Colors.BLUE_700, size=15),
                    ft.Text("Tipos y precios", size=12, weight="bold",
                            color=ft.Colors.BLUE_GREY_800),
                ], spacing=6),
                ft.Text("El precio se aplica a todas las habitaciones del tipo.",
                        size=10, color=ft.Colors.GREY_500, italic=True),
                header_tipos,
                ft.Column(
                    controls=[fila_tipo(t) for t in tipos],
                    spacing=0,
                ),
                ft.ElevatedButton(
                    "Guardar precios y aplicar a habitaciones",
                    icon=ft.Icons.SAVE,
                    bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
                    on_click=guardar_tipos,
                ),
            ], spacing=8),
            bgcolor=ft.Colors.BLUE_50,
            border=ft.border.all(1, ft.Colors.BLUE_200),
            border_radius=10,
            padding=16,
            width=380,
        )

        # ════════════════════════════════════════════════════════════════════
        # PANEL DERECHO — habitaciones (solo tipo, precio viene del tipo)
        # ════════════════════════════════════════════════════════════════════

        # Campos editables de habitaciones {hab_id: Dropdown}
        dropdowns_habs: dict = {}

        ESTADO_COLOR = {
            EstadoHabitacion.FREE:        ft.Colors.GREEN_700,
            EstadoHabitacion.OCCUPIED:    ft.Colors.RED_700,
            EstadoHabitacion.CLEANING:    ft.Colors.CYAN_700,
            EstadoHabitacion.RESERVED:    ft.Colors.AMBER_700,
            EstadoHabitacion.MAINTENANCE: ft.Colors.BLUE_GREY_600,
        }
        ESTADO_ETIQ = {
            EstadoHabitacion.FREE:        "LIBRE",
            EstadoHabitacion.OCCUPIED:    "OCUPADA",
            EstadoHabitacion.CLEANING:    "LIMPIEZA",
            EstadoHabitacion.RESERVED:    "RESERVADA",
            EstadoHabitacion.MAINTENANCE: "MTTO",
        }

        nombres_tipos = [t.nombre for t in tipos]

        def fila_hab(hab: Habitacion) -> ft.Container:
            precio_actual = precio_por_tipo.get(hab.tipo, _f(hab.precio_actual_usd))
            dd = ft.Dropdown(
                value=hab.tipo,
                options=[ft.dropdown.Option(n) for n in nombres_tipos],
                width=140, dense=True,
            )
            dropdowns_habs[hab.id] = dd

            color  = ESTADO_COLOR.get(hab.estado, ft.Colors.GREY_600)
            etiq   = ESTADO_ETIQ.get(hab.estado, "—")

            return ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text(f"{hab.numero}", size=14, weight="bold",
                                    color=ft.Colors.BLUE_GREY_800),
                            ft.Container(
                                content=ft.Text(etiq, size=7, weight="bold",
                                                color=ft.Colors.WHITE),
                                bgcolor=color,
                                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                                border_radius=4,
                            ),
                        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                           width=54),
                    ),
                    ft.VerticalDivider(width=1, color=ft.Colors.GREY_200),
                    dd,
                    ft.Text(f"${precio_actual:.2f}", size=12,
                            color=ft.Colors.GREY_600, width=70,
                            text_align=ft.TextAlign.RIGHT),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1, ft.Colors.GREY_200),
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                margin=ft.margin.only(bottom=4),
            )

        def guardar_habs(_):
            sesion = SesionLocal()
            try:
                tipos_bd = {t.nombre: t for t in sesion.query(TipoHabitacion).all()}
                for hab_id, dd in dropdowns_habs.items():
                    h   = sesion.get(Habitacion, hab_id)
                    tipo_obj = tipos_bd.get(dd.value)
                    if h and tipo_obj:
                        h.tipo              = tipo_obj.nombre
                        h.precio_base_usd   = tipo_obj.precio_base_usd
                        h.precio_actual_usd = tipo_obj.precio_actual_usd
                        h.capacidad_maxima  = tipo_obj.capacidad_default
                sesion.commit()
                self.pagina.open(ft.SnackBar(
                    ft.Text("Habitaciones actualizadas correctamente"),
                    bgcolor=ft.Colors.GREEN_700,
                ))
                self._refrescar()
            except Exception as err:
                sesion.rollback()
                self.pagina.open(ft.SnackBar(
                    ft.Text(f"Error: {err}"), bgcolor=ft.Colors.RED_700,
                ))
            finally:
                sesion.close()

        header_habs = ft.Container(
            content=ft.Row([
                ft.Text("Hab.", size=10, weight="bold",
                        color=ft.Colors.GREY_500, width=54),
                ft.Container(width=1),
                ft.Text("Tipo asignado", size=10, weight="bold",
                        color=ft.Colors.GREY_500, width=140),
                ft.Text("Precio/noche", size=10, weight="bold",
                        color=ft.Colors.GREY_500, width=70,
                        text_align=ft.TextAlign.RIGHT),
            ], spacing=8),
            bgcolor=ft.Colors.GREY_50,
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=ft.border_radius.only(top_left=8, top_right=8),
            border=ft.border.all(1, ft.Colors.GREY_200),
        )

        panel_habs = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.BED, color=ft.Colors.BLUE_700, size=15),
                    ft.Text(f"Habitaciones ({len(habitaciones)})",
                            size=12, weight="bold", color=ft.Colors.BLUE_GREY_800),
                    ft.Container(expand=True),
                    ft.Text("Cambia el tipo — el precio se asigna automáticamente.",
                            size=10, color=ft.Colors.GREY_500, italic=True),
                ], spacing=6),
                header_habs,
                ft.Column(
                    controls=[fila_hab(h) for h in habitaciones],
                    spacing=0,
                    scroll=ft.ScrollMode.AUTO,
                    height=480,
                ),
                ft.ElevatedButton(
                    "Guardar todos los cambios",
                    icon=ft.Icons.SAVE,
                    bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,
                    on_click=guardar_habs,
                ),
            ], spacing=8),
            bgcolor=ft.Colors.GREEN_50,
            border=ft.border.all(1, ft.Colors.GREEN_200),
            border_radius=10,
            padding=16,
            expand=True,
        )

        return ft.Column([
            ft.Row([
                panel_tipos,
                panel_habs,
            ], spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True, scroll=ft.ScrollMode.AUTO)

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES
    # ─────────────────────────────────────────────────────────────────────────

    def _actualizar_tasa(self):
        try:
            nueva = float(self._campo_tasa.value.replace(",", "."))
            sesion = SesionLocal()
            try:
                cfg = sesion.query(Configuracion).filter(
                    Configuracion.clave == "exchange_rate"
                ).first()
                if cfg:
                    cfg.valor = str(nueva)
                    sesion.commit()
                    self.estado_app["exchange_rate"] = nueva
                    self.pagina.open(ft.SnackBar(
                        ft.Text(f"Tasa actualizada: Bs. {nueva:,.2f}"),
                        bgcolor=ft.Colors.GREEN_700,
                    ))
                    self._refrescar()
            finally:
                sesion.close()
        except ValueError:
            self.pagina.open(ft.SnackBar(
                ft.Text("Ingresa un número válido para la tasa."),
                bgcolor=ft.Colors.RED_700,
            ))

    def _dlg_movimiento(self, es_ingreso: bool):
        titulo    = "Ingreso Manual" if es_ingreso else "Egreso / Gasto"
        color_btn = ft.Colors.GREEN_700 if es_ingreso else ft.Colors.RED_700

        campo_monto    = ft.TextField(
            label="Monto", prefix_text="$ ",
            keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True,
        )
        campo_concepto = ft.TextField(label="Concepto / Motivo", multiline=True)
        dd_moneda = ft.Dropdown(
            label="Moneda",
            options=[
                ft.dropdown.Option("USD", "Dólares ($)"),
                ft.dropdown.Option("BS",  "Bolívares (Bs)"),
            ],
            value="USD",
        )
        dd_caja = ft.Dropdown(
            label="Caja",
            options=[
                ft.dropdown.Option("principal", "Caja Principal"),
                ft.dropdown.Option("chica",     "Caja Chica"),
            ],
            value="chica",
        )

        def guardar(_):
            try:
                monto = float(campo_monto.value or 0)
                if monto <= 0:
                    campo_monto.error_text = "Monto inválido"
                    campo_monto.update()
                    return
            except ValueError:
                campo_monto.error_text = "Número inválido"
                campo_monto.update()
                return

            sesion = SesionLocal()
            try:
                caja   = sesion.query(Caja).first()
                moneda = dd_moneda.value
                fuente = dd_caja.value

                # Seleccionar campo de caja
                if moneda == "USD":
                    attr = "saldo_principal_usd" if fuente == "principal" else "caja_chica_usd"
                    saldo_actual = Decimal(str(getattr(caja, attr) or 0))
                    delta = Decimal(str(monto))
                    if not es_ingreso and saldo_actual < delta:
                        raise Exception(f"Saldo insuficiente (${float(saldo_actual):.2f} disponibles)")
                    setattr(caja, attr,
                            saldo_actual + delta if es_ingreso else saldo_actual - delta)
                else:
                    attr = "saldo_principal_bs" if fuente == "principal" else "caja_chica_bs"
                    saldo_actual = Decimal(str(getattr(caja, attr) or 0))
                    delta = Decimal(str(monto))
                    if not es_ingreso and saldo_actual < delta:
                        raise Exception(f"Saldo Bs insuficiente")
                    setattr(caja, attr,
                            saldo_actual + delta if es_ingreso else saldo_actual - delta)

                caja.ultima_actualizacion = datetime.now()
                sesion.commit()
                self.pagina.close(dlg)
                self.pagina.open(ft.SnackBar(
                    ft.Text("Movimiento registrado"),
                    bgcolor=ft.Colors.GREEN_700,
                ))
                self._refrescar()
            except Exception as err:
                sesion.rollback()
                self.pagina.open(ft.SnackBar(
                    ft.Text(str(err)), bgcolor=ft.Colors.RED_700,
                ))
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.ADD_CIRCLE if es_ingreso else ft.Icons.REMOVE_CIRCLE,
                        color=color_btn),
                ft.Text(titulo, color=color_btn),
            ], spacing=8),
            content=ft.Container(
                width=360,
                content=ft.Column([
                    ft.Row([dd_caja, dd_moneda], spacing=12),
                    campo_monto,
                    campo_concepto,
                ], spacing=14, tight=True),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton(
                    "Guardar",
                    bgcolor=color_btn, color=ft.Colors.WHITE,
                    on_click=guardar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _refrescar(self):
        """Reconstruye toda la pantalla con datos frescos de la BD."""
        self._construir()
        self.update()