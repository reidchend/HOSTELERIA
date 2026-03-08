# modules/rooms/details.py

import flet as ft
from datetime import timedelta
from sqlalchemy.orm import selectinload
from database.connection import SesionLocal
from database.models import (
    Habitacion, Estadia, Pago, Caja, MetodoPago,
    LineaCuenta, TipoLinea, TransaccionCobro,
)
from utils.calculos_financieros import leer_config_financiera, a_bs


class DialogoDetallesHabitacion:
    """
    Modal de detalle de una habitación OCUPADA.

    Sección superior: datos del huésped.
    Sección central:  historial de cuenta abierta con dos vistas:

      PENDIENTES — líneas sin cobrar con checkbox para seleccionar qué cobrar.
      HISTORIAL  — transacciones completadas, agrupadas por cobro (ExpansionTile)
                   mostrando: monto cobrado, saldo pendiente de esa transacción
                   y las líneas que incluyó.

    Al pulsar "Cobrar seleccionados" se abre DialogoPago con las líneas marcadas
    y sus IDs, para que al finalizar pueda marcarlas como canceladas y crear
    la TransaccionCobro correspondiente.
    """

    def __init__(self, pagina: ft.Page, habitacion: Habitacion,
                 al_solicitar_checkout, al_actualizar_grid=None):
        self.pagina                = pagina
        self.habitacion            = habitacion
        self.al_solicitar_checkout = al_solicitar_checkout
        # Callback opcional que el dashboard inyecta para que el diálogo
        # pueda notificar cuando cambia algo (renovación, cargo extra, cobro)
        # y el grid se actualice sin reconstruir toda la interfaz.
        self.al_actualizar_grid    = al_actualizar_grid
        self.dialogo               = None
        self.estadia_activa        = None

        # {linea_id: (Checkbox, monto_usd)}
        self._checkboxes: dict = {}
        self._texto_total_sel  = ft.Text("", weight="bold", size=13,
                                          color=ft.Colors.BLUE_900)

    # ═══════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN PRINCIPAL
    # ═══════════════════════════════════════════════════════════════════════

    def construir(self) -> ft.AlertDialog:
        sesion = SesionLocal()
        try:
            hab_datos = (
                sesion.query(Habitacion)
                .filter(Habitacion.id == self.habitacion.id)
                .options(
                    selectinload(Habitacion.estadias_activas)
                        .selectinload(Estadia.huespedes),
                    selectinload(Habitacion.estadias_activas)
                        .selectinload(Estadia.lineas_cuenta)
                        .selectinload(LineaCuenta.transaccion)
                        .selectinload(TransaccionCobro.lineas),
                    selectinload(Habitacion.estadias_activas)
                        .selectinload(Estadia.transacciones)
                        .selectinload(TransaccionCobro.lineas),
                    selectinload(Habitacion.estadias_activas)
                        .selectinload(Estadia.pagos),
                )
                .first()
            )

            if not hab_datos or not hab_datos.estadias_activas:
                return ft.AlertDialog(
                    title=ft.Text("Error"),
                    content=ft.Text("No se encontró información de esta habitación."),
                )

            estadia = next((e for e in hab_datos.estadias_activas if e.activa), None)
            if not estadia:
                return ft.AlertDialog(
                    title=ft.Text("Aviso"),
                    content=ft.Text("No hay una estadía activa en esta habitación."),
                )

            self.estadia_activa = estadia
            config = leer_config_financiera(sesion)
            tasa   = config.tasa_cambio

            titular      = estadia.huespedes[0] if estadia.huespedes else None
            acompanantes = estadia.huespedes[1:] if len(estadia.huespedes) > 1 else []

            # Separar líneas pendientes de las agrupadas en transacciones
            lineas_pendientes = [
                l for l in estadia.lineas_cuenta
                if not l.cancelada
            ]
            total_pendiente = sum(l.monto_usd for l in lineas_pendientes)

            total_pagado_bd = sum(
                -p.monto_usd if p.es_devolucion else p.monto_usd
                for p in estadia.pagos
            )

            # ── Encabezado del huésped ──────────────────────────────────────
            encabezado = self._encabezado_huesped(
                titular, acompanantes, estadia, tasa
            )

            # ── Tab de pendientes ───────────────────────────────────────────
            self._checkboxes      = {}
            self._texto_total_sel = ft.Text(
                f"Seleccionado: ${total_pendiente:.2f}",
                weight="bold", size=13, color=ft.Colors.BLUE_900,
            )

            tab_pendientes = self._construir_tab_pendientes(
                lineas_pendientes, tasa, total_pendiente
            )

            # ── Tab de historial ────────────────────────────────────────────
            tab_historial = self._construir_tab_historial(
                estadia.transacciones, tasa
            )

            # ── Tabs ────────────────────────────────────────────────────────
            tabs = ft.Tabs(
                selected_index=0,
                animation_duration=200,
                tabs=[
                    ft.Tab(
                        text=f"Pendientes ({len(lineas_pendientes)})",
                        icon=ft.Icons.PENDING_ACTIONS,
                        content=ft.Container(content=tab_pendientes, padding=8),
                    ),
                    ft.Tab(
                        text=f"Historial ({len(estadia.transacciones)})",
                        icon=ft.Icons.HISTORY,
                        content=ft.Container(content=tab_historial, padding=8),
                    ),
                ],
                expand=True,
            )

            # ── Barra de resumen ────────────────────────────────────────────
            barra = ft.Container(
                content=ft.Row([
                    self._chip_resumen("Total pendiente",
                                       f"${total_pendiente:.2f}",
                                       ft.Colors.RED_700 if total_pendiente > 0
                                       else ft.Colors.GREEN_700),
                    ft.VerticalDivider(width=16),
                    self._chip_resumen("Total pagado",
                                       f"${total_pagado_bd:.2f}",
                                       ft.Colors.GREEN_700),
                    ft.Container(expand=True),
                    self._texto_total_sel,
                ]),
                bgcolor=ft.Colors.GREY_50,
                padding=ft.padding.symmetric(horizontal=14, vertical=8),
                border_radius=8,
                border=ft.border.all(1, ft.Colors.GREY_200),
            )

            cuerpo = ft.Column([
                encabezado,
                tabs,
                barra,
            ], spacing=10, expand=True)

            self.dialogo = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(ft.Icons.BED, color="red"),
                    ft.Text(f"Habitación {self.habitacion.numero}"),
                    ft.Container(expand=True),
                    ft.TextButton(
                        "Renovar estadía",
                        icon=ft.Icons.AUTORENEW,
                        on_click=self.abrir_dialogo_renovacion,
                    ),
                ]),
                content=ft.Container(content=cuerpo, width=640, height=540),
                actions=[
                    ft.TextButton(
                        "Cerrar",
                        on_click=lambda _: self.pagina.close(self.dialogo),
                    ),
                    ft.ElevatedButton(
                        "Cargo Extra",
                        icon=ft.Icons.ADD_SHOPPING_CART,
                        on_click=self.agregar_cargo_extra,
                    ),
                    ft.ElevatedButton(
                        "Cobrar seleccionados",
                        icon=ft.Icons.PAYMENTS,
                        bgcolor=ft.Colors.GREEN_700, color="white",
                        on_click=self._abrir_cobro_seleccionados,
                    ),
                    ft.ElevatedButton(
                        "Check-Out",
                        icon=ft.Icons.EXIT_TO_APP,
                        bgcolor="red", color="white",
                        on_click=lambda _: self.al_solicitar_checkout(self.habitacion),
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )

            self._marcar_todos_pendientes()
            return self.dialogo

        finally:
            sesion.close()

    # ═══════════════════════════════════════════════════════════════════════
    # ENCABEZADO DEL HUÉSPED
    # ═══════════════════════════════════════════════════════════════════════

    def _encabezado_huesped(self, titular, acompanantes, estadia, tasa) -> ft.Container:
        # ── Datos completos del titular ───────────────────────────────────────
        credito_titular = round(titular.credito_usd or 0.0, 2) if titular else 0.0

        detalles_titular = []
        if titular:
            detalles_titular = [
                (ft.Icons.BADGE,           f"Doc: {titular.documento}"),
                (ft.Icons.CAKE,            f"Nac: {titular.fecha_nacimiento.strftime('%d/%m/%Y') if titular.fecha_nacimiento else '—'}"),
                (ft.Icons.FLAG,            f"{titular.nacionalidad or '—'}"),
                (ft.Icons.WORK_OUTLINE,    f"{titular.profesion or '—'}"),
                (ft.Icons.PHONE,           f"{titular.telefono or '—'}"),
                (ft.Icons.DIRECTIONS_CAR,  f"{titular.vehiculo or '—'}"),
            ]

        filas_titular = [
            ft.Row([
                ft.Icon(icono, size=13, color=ft.Colors.BLUE_600),
                ft.Text(texto, size=11, color=ft.Colors.GREY_700),
            ], spacing=5)
            for icono, texto in detalles_titular
        ]

        # ── Acompañantes con cédula ───────────────────────────────────────────
        chips_acomp = []
        for ac in acompanantes:
            chips_acomp.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PERSON_OUTLINE, size=11, color=ft.Colors.BLUE_700),
                        ft.Text(ac.nombre_completo, size=10, weight="bold"),
                        ft.Text(f"({ac.documento})", size=10, color=ft.Colors.GREY_600),
                    ], spacing=4),
                    bgcolor=ft.Colors.BLUE_50,
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                    border_radius=10,
                    border=ft.border.all(1, ft.Colors.BLUE_100),
                )
            )

        # ── Chip de saldo a favor ─────────────────────────────────────────────
        chip_saldo = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=13,
                        color=ft.Colors.WHITE if credito_titular > 0.01 else ft.Colors.GREY_500),
                ft.Text(
                    f"Saldo a favor: ${credito_titular:.2f}",
                    size=11, weight="bold",
                    color=ft.Colors.WHITE if credito_titular > 0.01 else ft.Colors.GREY_500,
                ),
            ], spacing=5),
            bgcolor=ft.Colors.GREEN_700 if credito_titular > 0.01 else ft.Colors.GREY_100,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=8,
        )

        return ft.Container(
            content=ft.Column([
                # Fila superior: nombre + estadía + saldo
                ft.Row([
                    ft.Row([
                        ft.Icon(ft.Icons.PERSON, color=ft.Colors.BLUE_800, size=18),
                        ft.Text(
                            titular.nombre_completo if titular else "N/A",
                            weight="bold", size=15,
                        ),
                    ], spacing=5, expand=True),
                    chip_saldo,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text(
                    f"{estadia.entrada.strftime('%d/%m/%Y')} → {estadia.salida.strftime('%d/%m/%Y')}",
                    size=11, color=ft.Colors.GREY_600,
                ),
                ft.Divider(height=6, color=ft.Colors.BLUE_100),
                # Datos personales en dos columnas
                ft.Row(
                    controls=[
                        ft.Column(filas_titular[:3], spacing=4, expand=True),
                        ft.Column(filas_titular[3:], spacing=4, expand=True),
                    ],
                    spacing=10,
                ) if filas_titular else ft.Container(),
                # Acompañantes
                ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.GROUP, size=13, color=ft.Colors.BLUE_600),
                        ft.Text("Acompañantes:", size=11, color=ft.Colors.GREY_600, italic=True),
                    ], spacing=4),
                    ft.Row(controls=chips_acomp, spacing=6, wrap=True),
                ], spacing=4) if acompanantes else ft.Container(),
            ], spacing=6),
            bgcolor=ft.Colors.BLUE_50,
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            border_radius=10,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 1 — PENDIENTES (con checkboxes)
    # ═══════════════════════════════════════════════════════════════════════

    def _construir_tab_pendientes(
        self, lineas: list, tasa: float, total: float
    ) -> ft.Column:

        if not lineas:
            return ft.Column([
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE,
                                size=40, color=ft.Colors.GREEN_400),
                        ft.Text("No hay cargos pendientes",
                                size=13, color=ft.Colors.GREY_500,
                                text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=8),
                    padding=30,
                    alignment=ft.alignment.center,
                )
            ])

        filas = [self._fila_pendiente(l, tasa) for l in lineas]

        return ft.Column([
            ft.Row([
                ft.TextButton(
                    "Marcar todos",
                    icon=ft.Icons.CHECK_BOX_OUTLINED,
                    on_click=lambda _: self._marcar_todos(True),
                ),
                ft.TextButton(
                    "Desmarcar todos",
                    icon=ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                    on_click=lambda _: self._marcar_todos(False),
                ),
            ]),
            ft.Column(controls=filas, spacing=5, scroll=ft.ScrollMode.AUTO),
        ], spacing=4, expand=True)

    def _fila_pendiente(self, linea: LineaCuenta, tasa: float) -> ft.Container:
        """Una fila con checkbox para las líneas pendientes de cobro."""
        TIPO_CFG = {
            TipoLinea.HOSPEDAJE:       (ft.Icons.BED_OUTLINED,     ft.Colors.BLUE_700,   "Hospedaje"),
            TipoLinea.CARGO_EXTRA:     (ft.Icons.ROOM_SERVICE,     ft.Colors.ORANGE_700, "Servicio c/IVA"),
            TipoLinea.SALDO_PENDIENTE: (ft.Icons.PENDING_ACTIONS,  ft.Colors.RED_700,    "Deuda anterior"),
        }
        icono, color, etiqueta = TIPO_CFG.get(
            linea.tipo,
            (ft.Icons.CIRCLE, ft.Colors.GREY_500, "Otro"),
        )

        cb = ft.Checkbox(
            value=True,
            on_change=lambda _: self._actualizar_total_seleccionado(),
        )
        self._checkboxes[linea.id] = (cb, linea.monto_usd)

        return ft.Container(
            content=ft.Row([
                cb,
                ft.Icon(icono, size=15, color=color),
                ft.Column([
                    ft.Text(linea.concepto, size=11, weight="bold"),
                    ft.Row([
                        ft.Container(
                            content=ft.Text(etiqueta, size=9, color=color),
                            bgcolor=ft.Colors.with_opacity(0.1, color),
                            padding=ft.padding.symmetric(horizontal=5, vertical=1),
                            border_radius=4,
                        ),
                        ft.Text(
                            linea.creado_en.strftime("%d/%m/%Y %H:%M"),
                            size=9, color=ft.Colors.GREY_400,
                        ),
                    ], spacing=6),
                ], spacing=2, expand=True),
                ft.Column([
                    ft.Text(f"${linea.monto_usd:.2f}", size=13,
                            weight="bold", color=ft.Colors.RED_700,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Text(f"Bs.{a_bs(linea.monto_usd, tasa):,.0f}",
                            size=9, color=ft.Colors.GREY_400,
                            text_align=ft.TextAlign.RIGHT),
                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=ft.Colors.WHITE,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_radius=8,
            border=ft.border.all(1, ft.Colors.BLUE_100),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 2 — HISTORIAL (agrupado por TransaccionCobro)
    # ═══════════════════════════════════════════════════════════════════════

    def _construir_tab_historial(
        self, transacciones: list, tasa: float
    ) -> ft.Column:

        if not transacciones:
            return ft.Column([
                ft.Container(
                    content=ft.Text(
                        "Aún no se han registrado cobros.",
                        size=12, italic=True, color=ft.Colors.GREY_400,
                    ),
                    padding=20,
                )
            ])

        # Ordenar del más reciente al más antiguo
        txs = sorted(transacciones, key=lambda t: t.creado_en, reverse=True)
        tiles = [self._tile_transaccion(i, tx, tasa)
                 for i, tx in enumerate(txs, 1)]

        return ft.Column(
            controls=tiles,
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
        )

    def _tile_transaccion(
        self, numero: int, tx: TransaccionCobro, tasa: float
    ) -> ft.ExpansionTile:
        """ExpansionTile que representa un cobro completo o parcial."""

        es_completo  = tx.saldo_pendiente <= 0.01
        color_estado = ft.Colors.GREEN_700 if es_completo else ft.Colors.ORANGE_700
        texto_estado = "PAGADO" if es_completo else f"PARCIAL (debe ${tx.saldo_pendiente:.2f})"
        icono_estado = ft.Icons.CHECK_CIRCLE if es_completo else ft.Icons.TIMELAPSE

        # Cabecera del tile
        titulo = ft.Row([
            ft.Icon(icono_estado, color=color_estado, size=16),
            ft.Column([
                ft.Text(
                    f"Factura #{numero}  —  {tx.creado_en.strftime('%d/%m/%Y %H:%M')}",
                    size=12, weight="bold",
                ),
                ft.Row([
                    ft.Text(f"Cobrado: ${tx.total_pagado:.2f}", size=11,
                            color=ft.Colors.GREEN_700),
                    ft.Text(" · ", size=11, color=ft.Colors.GREY_400),
                    ft.Text(
                        f"Pendiente: ${tx.saldo_pendiente:.2f}",
                        size=11,
                        color=ft.Colors.ORANGE_700 if tx.saldo_pendiente > 0.01
                        else ft.Colors.GREY_400,
                    ),
                ], spacing=2),
            ], spacing=2, expand=True),
            ft.Container(
                content=ft.Text(texto_estado, size=9, weight="bold",
                                color=ft.Colors.WHITE),
                bgcolor=color_estado,
                padding=ft.padding.symmetric(horizontal=7, vertical=3),
                border_radius=8,
            ),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # Líneas incluidas en esta transacción
        lineas_tx = [l for l in tx.lineas
                     if l.tipo != TipoLinea.SALDO_PENDIENTE or not l.cancelada]

        filas_lineas = []
        for linea in lineas_tx:
            TIPO_CFG = {
                TipoLinea.HOSPEDAJE:       (ft.Icons.BED_OUTLINED,    ft.Colors.BLUE_700,   "Hospedaje"),
                TipoLinea.CARGO_EXTRA:     (ft.Icons.ROOM_SERVICE,    ft.Colors.ORANGE_700, "Servicio"),
                TipoLinea.SALDO_PENDIENTE: (ft.Icons.PENDING_ACTIONS, ft.Colors.RED_700,    "Deuda"),
            }
            icono, color, etiq = TIPO_CFG.get(
                linea.tipo, (ft.Icons.CIRCLE, ft.Colors.GREY_500, "")
            )
            cancelada = linea.cancelada

            filas_lineas.append(ft.Container(
                content=ft.Row([
                    ft.Icon(icono, size=13, color=color
                            if cancelada else ft.Colors.ORANGE_700),
                    ft.Text(linea.concepto, size=11, expand=True,
                            color=ft.Colors.GREY_600 if cancelada
                            else ft.Colors.BLACK87),
                    ft.Icon(
                        ft.Icons.CHECK if cancelada else ft.Icons.PENDING,
                        size=12,
                        color=ft.Colors.GREEN_600 if cancelada
                        else ft.Colors.ORANGE_700,
                    ),
                    ft.Text(
                        f"${linea.monto_usd:.2f}",
                        size=11, weight="bold",
                        color=ft.Colors.GREY_500 if cancelada
                        else ft.Colors.RED_700,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ], spacing=6),
                padding=ft.padding.symmetric(horizontal=12, vertical=5),
                bgcolor=ft.Colors.GREY_50 if cancelada else ft.Colors.ORANGE_50,
                border_radius=6,
            ))

        return ft.ExpansionTile(
            title=titulo,
            initially_expanded=False,
            bgcolor=ft.Colors.WHITE,
            collapsed_bgcolor=ft.Colors.WHITE,
            controls=[
                ft.Container(
                    content=ft.Column(controls=filas_lineas, spacing=4),
                    padding=ft.padding.only(left=16, right=8, bottom=8),
                )
            ],
        )

    # ═══════════════════════════════════════════════════════════════════════
    # LÓGICA DE SELECCIÓN
    # ═══════════════════════════════════════════════════════════════════════

    def _marcar_todos_pendientes(self):
        for cb, _ in self._checkboxes.values():
            cb.value = True
        self._actualizar_total_seleccionado()

    def _marcar_todos(self, valor: bool):
        for cb, _ in self._checkboxes.values():
            cb.value = valor
        self._actualizar_total_seleccionado()
        self.pagina.update()

    def _actualizar_total_seleccionado(self):
        total = sum(
            monto for cb, monto in self._checkboxes.values() if cb.value
        )
        self._texto_total_sel.value = f"Seleccionado: ${total:.2f}"
        try:
            self._texto_total_sel.update()
        except Exception:
            pass

    def _ids_seleccionados(self) -> list:
        return [
            lid for lid, (cb, _) in self._checkboxes.items() if cb.value
        ]

    def _total_seleccionado(self) -> float:
        return sum(
            monto for cb, monto in self._checkboxes.values() if cb.value
        )

    # ═══════════════════════════════════════════════════════════════════════
    # COBRO DE LAS LÍNEAS SELECCIONADAS
    # ═══════════════════════════════════════════════════════════════════════

    def _abrir_cobro_seleccionados(self, evento):
        ids   = self._ids_seleccionados()
        monto = self._total_seleccionado()

        if not ids:
            self.pagina.open(ft.SnackBar(
                ft.Text("Selecciona al menos una línea pendiente para cobrar."),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return

        self.pagina.close(self.dialogo)

        from modules.finance.payment_dialog import DialogoPago
        DialogoPago(
            self.pagina,
            self.estadia_activa,
            total_a_pagar = monto,
            al_completar  = self.refrescar_detalles,
            lineas_ids    = ids,
        ).mostrar()

    # ═══════════════════════════════════════════════════════════════════════
    # RENOVACIÓN
    # ═══════════════════════════════════════════════════════════════════════

    def abrir_dialogo_renovacion(self, evento):
        campo_dias = ft.TextField(
            label="Días a renovar", value="1",
            suffix_text="noche(s)", keyboard_type=ft.KeyboardType.NUMBER,
        )

        def confirmar_renovacion(evento):
            try:
                dias = int(campo_dias.value)
                if dias <= 0:
                    return
                sesion = SesionLocal()
                try:
                    estadia_bd    = sesion.get(Estadia, self.estadia_activa.id)
                    habitacion_bd = sesion.get(Habitacion, self.habitacion.id)
                    nueva_entrada = estadia_bd.salida
                    nueva_salida  = estadia_bd.salida + timedelta(days=dias)
                    estadia_bd.salida = nueva_salida

                    config     = leer_config_financiera(sesion)
                    precio_n   = (
                        habitacion_bd.precio_actual_usd
                        or habitacion_bd.precio_base_usd
                    )
                    # Mismo cálculo que el check-in: precio base + IVA
                    from decimal import Decimal, ROUND_HALF_UP
                    _D = lambda x: Decimal(str(x))
                    monto_base  = dias * precio_n
                    factor_iva  = config.porcentaje_iva / 100
                    monto_total = float(
                        (_D(monto_base) * (1 + _D(factor_iva)))
                        .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    )

                    sesion.add(LineaCuenta(
                        estadia_id = estadia_bd.id,
                        tipo       = TipoLinea.HOSPEDAJE,
                        concepto   = (
                            f"Renovación — Hab. {habitacion_bd.numero} "
                            f"({dias} noche{'s' if dias > 1 else ''}) "
                            f"{nueva_entrada.strftime('%d/%m/%Y')} → "
                            f"{nueva_salida.strftime('%d/%m/%Y')}"
                        ),
                        monto_usd  = monto_total,
                        cancelada  = False,
                    ))
                    sesion.commit()
                    self.pagina.close(modal_renovacion)
                    self.refrescar_detalles()
                    self.pagina.open(ft.SnackBar(
                        ft.Text(f"Renovación registrada: {dias} día(s) — ${monto_total:.2f}"),
                        bgcolor=ft.Colors.GREEN_700,
                    ))
                except Exception as err:
                    sesion.rollback()
                    self.pagina.open(ft.SnackBar(ft.Text(str(err)), bgcolor="red"))
                finally:
                    sesion.close()
            except ValueError:
                pass

        modal_renovacion = ft.AlertDialog(
            title=ft.Text("Renovar Estadía"),
            content=campo_dias,
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(modal_renovacion)),
                ft.ElevatedButton("Confirmar", on_click=confirmar_renovacion),
            ],
        )
        self.pagina.open(modal_renovacion)

    # ═══════════════════════════════════════════════════════════════════════
    # VUELTO
    # ═══════════════════════════════════════════════════════════════════════

    def abrir_selector_devolucion(self, monto_usd: float):
        selector = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="principal", label="Caja Principal (Efectivo)"),
                ft.Radio(value="chica",     label="Caja Chica (Recepción)"),
                ft.Radio(value="pm_admin",  label="Pago Móvil (Administración)"),
            ])
        )
        selector.value = "principal"

        def procesar(evento):
            sesion = SesionLocal()
            try:
                fuente = selector.value
                caja   = sesion.query(Caja).first()
                desc   = ""
                metodo = MetodoPago.CASH_USD

                if fuente == "principal":
                    if caja.saldo_principal_usd < monto_usd:
                        raise Exception("Caja Principal sin fondos suficientes.")
                    caja.saldo_principal_usd -= monto_usd
                    desc = "Vuelto desde Caja Principal"
                elif fuente == "chica":
                    if caja.caja_chica_usd < monto_usd:
                        raise Exception("Caja Chica sin fondos suficientes.")
                    caja.caja_chica_usd -= monto_usd
                    desc = "Vuelto desde Caja Chica"
                elif fuente == "pm_admin":
                    metodo = MetodoPago.PAGO_MOVIL
                    desc   = "Vuelto vía Pago Móvil"

                config = leer_config_financiera(sesion)
                sesion.add(Pago(
                    estadia_id    = self.estadia_activa.id,
                    monto_usd     = monto_usd,
                    monto_bs      = a_bs(monto_usd, config.tasa_cambio),
                    tasa_cambio   = config.tasa_cambio,
                    metodo        = metodo,
                    es_devolucion = True,
                    descripcion   = desc,
                ))
                sesion.commit()
                self.pagina.close(modal_dev)
                self.refrescar_detalles()
                self.pagina.open(ft.SnackBar(
                    ft.Text("Vuelto entregado"), bgcolor="green"
                ))
            except Exception as err:
                self.pagina.open(ft.SnackBar(ft.Text(str(err)), bgcolor="red"))
            finally:
                sesion.close()

        modal_dev = ft.AlertDialog(
            title=ft.Text("Seleccionar Origen del Vuelto"),
            content=ft.Column([ft.Text(f"Monto: ${monto_usd:.2f}"), selector],
                               tight=True),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(modal_dev)),
                ft.ElevatedButton("Procesar", on_click=procesar,
                                  bgcolor="orange", color="white"),
            ],
        )
        self.pagina.open(modal_dev)

    # ═══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _chip_resumen(self, etiqueta: str, valor: str, color) -> ft.Column:
        return ft.Column([
            ft.Text(etiqueta, size=10, color=ft.Colors.GREY_600),
            ft.Text(valor, size=16, weight="bold", color=color),
        ], spacing=1)

    def agregar_cargo_extra(self, evento):
        from modules.finance.extra_charges import DialogoCargoExtra
        DialogoCargoExtra(
            self.pagina, self.estadia_activa,
            al_completar=self.refrescar_detalles,
        ).mostrar()

    def refrescar_detalles(self):
        """
        Se llama tras cualquier operación que modifique la estadía
        (cobro, cargo extra, renovación). Hace dos cosas:
        1. Reabre el diálogo con datos frescos de la BD.
        2. Notifica al dashboard para que actualice el grid y las tarjetas
           de resumen sin reconstruir toda la interfaz — así los indicadores
           de cuentas pendientes y la fecha de salida aparecen al instante.
        """
        if self.dialogo:
            self.pagina.close(self.dialogo)
        # Notificar al dashboard ANTES de reabrir el diálogo, para que el
        # grid ya muestre el estado actualizado cuando el usuario lo cierre.
        if self.al_actualizar_grid:
            self.al_actualizar_grid()
        self.mostrar()

    def mostrar(self):
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)