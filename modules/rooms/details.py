# modules/rooms/details.py

import flet as ft
from datetime import datetime, timedelta
from sqlalchemy.orm import selectinload
from database.connection import SesionLocal
from database.models import Habitacion, Estadia, Pago, Configuracion, Caja, MetodoPago
from modules.finance.payment_dialog import DialogoPago


class DialogoDetallesHabitacion:
    """
    Modal de detalle de una habitación OCUPADA.
    Muestra la ficha del huésped, el estado financiero de la cuenta y
    los botones para cobrar, añadir cargos extra, renovar estadía o hacer check-out.
    """

    def __init__(self, pagina: ft.Page, habitacion: Habitacion, al_solicitar_checkout):
        self.pagina              = pagina
        self.habitacion          = habitacion
        self.al_solicitar_checkout = al_solicitar_checkout
        self.dialogo             = None
        self.estadia_activa      = None

    def obtener_tasa_cambio(self, sesion) -> float:
        """Lee la tasa de cambio vigente desde la tabla de configuración."""
        config = sesion.query(Configuracion).filter(Configuracion.clave == "exchange_rate").first()
        if config and config.valor:
            try:
                return float(config.valor)
            except ValueError:
                pass
        return 1.0

    def construir(self) -> ft.AlertDialog:
        """Carga los datos frescos desde la BD y construye el diálogo de detalles."""
        sesion = SesionLocal()
        try:
            hab_datos = (
                sesion.query(Habitacion)
                .filter(Habitacion.id == self.habitacion.id)
                .options(
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.huespedes),
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.cargos_extras),
                    selectinload(Habitacion.estadias_activas).selectinload(Estadia.pagos),
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
            tasa = self.obtener_tasa_cambio(sesion)

            # Leer porcentaje de IVA desde configuracion (misma fuente que payment_dialog)
            config_iva     = sesion.query(Configuracion).filter(
                Configuracion.clave == "tax_percentage"
            ).first()
            porcentaje_iva = float(config_iva.valor) if config_iva else 0.0

            # ── Cálculos financieros ──────────────────────────────────────────
            titular      = estadia.huespedes[0] if estadia.huespedes else None
            acompanantes = estadia.huespedes[1:] if len(estadia.huespedes) > 1 else []

            dias = max(1, (estadia.salida.date() - estadia.entrada.date()).days)
            precio_noche  = (
                hab_datos.precio_actual_usd if hab_datos.precio_actual_usd
                else hab_datos.precio_base_usd
            )
            subtotal_habitacion = dias * precio_noche
            total_extras  = sum(c.monto_usd for c in estadia.cargos_extras)
            total_pagado  = sum(
                -p.monto_usd if p.es_devolucion else p.monto_usd
                for p in estadia.pagos
            )
            subtotal = subtotal_habitacion + total_extras
            monto_iva = round(subtotal * (porcentaje_iva / 100), 2)
            # total_cuenta incluye IVA para que coincida con lo que cobra payment_dialog
            total_cuenta    = subtotal + monto_iva
            saldo_pendiente = total_cuenta - total_pagado

            es_favor  = saldo_pendiente < -0.01
            color_saldo = (
                ft.Colors.GREEN_700 if es_favor
                else (ft.Colors.RED_700 if saldo_pendiente > 0.01 else ft.Colors.BLUE_GREY_700)
            )
            texto_saldo = "Saldo a Favor:" if es_favor else "Saldo Pendiente:"

            # ── Diseño del contenido ──────────────────────────────────────────
            cuerpo = ft.Column([
                # Bloque de fechas y días
                ft.Container(
                    content=ft.Row([
                        self.celda_info("Entrada",  estadia.entrada.strftime("%d/%m/%Y")),
                        ft.VerticalDivider(),
                        self.celda_info("Salida Prevista", estadia.salida.strftime("%d/%m/%Y")),
                        ft.VerticalDivider(),
                        ft.Column([
                            ft.Text("Días", size=11, color=ft.Colors.BLUE_GREY_400),
                            ft.Row([
                                ft.Text(str(dias), weight="bold", size=14, color=ft.Colors.BLUE),
                                ft.IconButton(
                                    ft.Icons.AUTORENEW, icon_size=16,
                                    tooltip="Añadir días / Renovar",
                                    on_click=self.abrir_dialogo_renovacion,
                                ),
                            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER),
                        ], expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ], height=50),
                    bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=10,
                ),

                # Datos del titular
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PERSON, color=ft.Colors.BLUE_800),
                        ft.Column([
                            ft.Text(
                                titular.nombre_completo if titular else "N/A",
                                weight="bold", size=16,
                            ),
                            ft.Text(
                                f"Titular  ·  Doc: {titular.documento if titular else 'S/D'}",
                                size=12,
                            ),
                        ], spacing=0),
                    ]),
                    padding=ft.padding.only(bottom=5),
                ),

                # Acompañantes (desplegable)
                ft.ExpansionTile(
                    title=ft.Text(f"Acompañantes ({len(acompanantes)})", size=13, weight="bold"),
                    leading=ft.Icon(ft.Icons.GROUP_OUTLINED, size=20),
                    initially_expanded=False,
                    controls=(
                        [
                            ft.ListTile(
                                dense=True,
                                title=ft.Text(ac.nombre_completo, size=13),
                                subtitle=ft.Text(f"Doc: {ac.documento}", size=11),
                                leading=ft.Icon(ft.Icons.SUBDIRECTORY_ARROW_RIGHT, size=16),
                            )
                            for ac in acompanantes
                        ] if acompanantes else [
                            ft.Container(
                                content=ft.Text("Sin acompañantes registrados", size=12, italic=True),
                                padding=10,
                            )
                        ]
                    ),
                ),

                # Bloque financiero
                ft.Container(
                    content=ft.Column([
                        # Desglose: subtotal + IVA + total
                        ft.Row([
                            ft.Text("Subtotal:", size=11, color=ft.Colors.GREY_700, expand=True),
                            ft.Text(f"${subtotal:.2f}", size=11, text_align=ft.TextAlign.RIGHT),
                        ]),
                        ft.Row([
                            ft.Text(f"IVA ({porcentaje_iva:.0f}%):", size=11, color=ft.Colors.GREY_700, expand=True),
                            ft.Text(f"${monto_iva:.2f}", size=11, text_align=ft.TextAlign.RIGHT),
                        ]) if porcentaje_iva > 0 else ft.Container(height=0),
                        ft.Row([
                            ft.Text("Total c/ IVA:", size=12, weight="bold", color=ft.Colors.BLUE_900, expand=True),
                            ft.Text(f"${total_cuenta:.2f}", size=12, weight="bold",
                                    color=ft.Colors.BLUE_900, text_align=ft.TextAlign.RIGHT),
                        ]),
                        ft.Divider(height=6, color=ft.Colors.GREY_300),
                        ft.Row([
                            ft.Text("Estado de Cuenta:", size=14, weight="bold"),
                            ft.Column([
                                ft.Text(
                                    f"{texto_saldo} ${abs(saldo_pendiente):.2f}",
                                    size=18, weight="bold", color=color_saldo,
                                ),
                                ft.Text(
                                    f"Bs. {abs(saldo_pendiente * tasa):,.2f}",
                                    size=12, color=color_saldo,
                                ),
                            ], horizontal_alignment=ft.CrossAxisAlignment.END),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

                        ft.Row([
                            ft.ElevatedButton(
                                "Cargo Extra", icon=ft.Icons.ADD_SHOPPING_CART,
                                on_click=self.agregar_cargo_extra,
                                expand=True,
                            ),
                            ft.ElevatedButton(
                                "Ir a Cobrar", icon=ft.Icons.PAYMENTS,
                                bgcolor=ft.Colors.GREEN_700, color="white",
                                on_click=lambda _: self.abrir_modulo_cobro(saldo_pendiente),
                                expand=True,
                                visible=saldo_pendiente > 0.01,
                            ),
                            ft.ElevatedButton(
                                "Entregar Vuelto", icon=ft.Icons.MONEY_OFF,
                                bgcolor=ft.Colors.ORANGE_800, color="white",
                                on_click=lambda _: self.abrir_selector_devolucion(abs(saldo_pendiente)),
                                expand=True,
                                visible=es_favor,
                            ),
                        ], spacing=10),
                    ]),
                    padding=15, bgcolor=ft.Colors.GREY_100, border_radius=12,
                ),

                ft.Text("Resumen de Consumos", weight="bold", size=14),
                self.construir_tabla_consumos(estadia),
            ], scroll=ft.ScrollMode.AUTO, tight=True, spacing=15)

            self.dialogo = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(ft.Icons.BED, color="red"),
                    ft.Text(f"Habitación {self.habitacion.numero}"),
                ]),
                content=ft.Container(content=cuerpo, width=550),
                actions=[
                    ft.TextButton("Cerrar", on_click=lambda _: self.pagina.close(self.dialogo)),
                    ft.ElevatedButton(
                        "Check-Out Final", icon=ft.Icons.EXIT_TO_APP,
                        bgcolor="red", color="white",
                        on_click=lambda _: self.al_solicitar_checkout(self.habitacion),
                        disabled=saldo_pendiente > 0.01,
                    ),
                ],
            )
            return self.dialogo

        finally:
            sesion.close()

    def celda_info(self, etiqueta: str, valor: str) -> ft.Column:
        """Devuelve un bloque de dos líneas: etiqueta pequeña + valor en negrita."""
        return ft.Column([
            ft.Text(etiqueta, size=11, color=ft.Colors.BLUE_GREY_400),
            ft.Text(valor, weight="bold", size=14),
        ], expand=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    def construir_tabla_consumos(self, estadia: Estadia):
        """Tabla de consumos facturados: hospedaje base + cargos extra."""
        filas = [
            ft.DataRow(cells=[
                ft.DataCell(ft.Text("Hospedaje Base")),
                ft.DataCell(ft.Text(f"$ {self.habitacion.precio_base_usd:.2f} (x día)")),
            ])
        ]
        for cargo in estadia.cargos_extras:
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(cargo.nombre_servicio)),
                ft.DataCell(ft.Text(f"$ {cargo.monto_usd:.2f}")),
            ]))

        if not estadia.cargos_extras and not estadia.pagos:
            return ft.Text("No hay cargos adicionales.", size=12, italic=True)

        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Concepto")),
                ft.DataColumn(ft.Text("Monto USD")),
            ],
            rows=filas,
        )

    # ── LÓGICA DE RENOVACIÓN ────────────────────────────────────────────────

    def abrir_dialogo_renovacion(self, evento):
        """Permite extender la estadía agregando más noches."""
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
                estadia = sesion.query(Estadia).filter(Estadia.id == self.estadia_activa.id).first()
                estadia.salida = estadia.salida + timedelta(days=dias)
                sesion.commit()
                sesion.close()
                self.pagina.close(modal_renovacion)
                self.refrescar_detalles()
                self.pagina.open(ft.SnackBar(ft.Text(f"Estadía extendida {dias} día(s).")))
            except Exception:
                pass

        modal_renovacion = ft.AlertDialog(
            title=ft.Text("Renovar Estadía"),
            content=campo_dias,
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(modal_renovacion)),
                ft.ElevatedButton("Confirmar", on_click=confirmar_renovacion),
            ],
        )
        self.pagina.open(modal_renovacion)

    # ── LÓGICA DE DEVOLUCIÓN DE VUELTO ──────────────────────────────────────

    def abrir_selector_devolucion(self, monto_usd: float):
        """Selecciona la caja desde donde se entregará el vuelto."""
        selector_fuente = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="principal", label="Caja Principal (Efectivo)"),
                ft.Radio(value="chica",     label="Caja Chica (Recepción)"),
                ft.Radio(value="pm_admin",  label="Pago Móvil (Administración)"),
            ])
        )
        selector_fuente.value = "principal"

        def procesar_devolucion(evento):
            sesion = SesionLocal()
            try:
                fuente = selector_fuente.value
                caja = sesion.query(Caja).first()
                descripcion = ""
                metodo_pago = MetodoPago.CASH_USD

                if fuente == "principal":
                    if caja.saldo_principal_usd < monto_usd:
                        raise Exception("Caja Principal sin fondos suficientes.")
                    caja.saldo_principal_usd -= monto_usd
                    descripcion = "Vuelto devuelto desde Caja Principal"
                elif fuente == "chica":
                    if caja.caja_chica_usd < monto_usd:
                        raise Exception("Caja Chica sin fondos suficientes.")
                    caja.caja_chica_usd -= monto_usd
                    descripcion = "Vuelto devuelto desde Caja Chica"
                elif fuente == "pm_admin":
                    metodo_pago = MetodoPago.PAGO_MOVIL
                    descripcion = "Vuelto devuelto vía Pago Móvil del Administrador"

                sesion.add(Pago(
                    estadia_id    = self.estadia_activa.id,
                    monto_usd     = monto_usd,
                    tasa_cambio   = self.obtener_tasa_cambio(sesion),
                    metodo        = metodo_pago,
                    es_devolucion = True,
                    descripcion   = descripcion,
                ))
                sesion.commit()
                self.pagina.close(modal_devolucion)
                self.refrescar_detalles()
                self.pagina.open(ft.SnackBar(ft.Text("Vuelto entregado exitosamente"), bgcolor="green"))

            except Exception as error:
                self.pagina.open(ft.SnackBar(ft.Text(str(error)), bgcolor="red"))
            finally:
                sesion.close()

        modal_devolucion = ft.AlertDialog(
            title=ft.Text("Seleccionar Origen del Vuelto"),
            content=ft.Column([
                ft.Text(f"Monto a entregar: ${monto_usd:.2f}"),
                selector_fuente,
            ], tight=True),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(modal_devolucion)),
                ft.ElevatedButton(
                    "Procesar", on_click=procesar_devolucion,
                    bgcolor="orange", color="white",
                ),
            ],
        )
        self.pagina.open(modal_devolucion)

    # ── NAVEGACIÓN ──────────────────────────────────────────────────────────

    def abrir_modulo_cobro(self, saldo_pendiente: float):
        """Cierra este diálogo y abre el módulo de cobro."""
        self.pagina.close(self.dialogo)
        modulo_cobro = DialogoPago(
            self.pagina, self.estadia_activa,
            total_a_pagar=saldo_pendiente,
            al_completar=self.refrescar_detalles,
        )
        modulo_cobro.mostrar()

    def agregar_cargo_extra(self, evento):
        """Abre el módulo de cargos extra para esta estadía."""
        from modules.finance.extra_charges import DialogoCargoExtra
        dialogo = DialogoCargoExtra(
            self.pagina, self.estadia_activa,
            al_completar=self.refrescar_detalles,
        )
        dialogo.mostrar()

    def refrescar_detalles(self):
        """Cierra el diálogo actual y vuelve a abrirlo con datos frescos de la BD."""
        if self.dialogo:
            self.pagina.close(self.dialogo)
        self.mostrar()

    def mostrar(self):
        """Construye y abre el diálogo de detalles."""
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)