# modules/finance/extra_charges.py

import flet as ft
from utils.decimal_utils import D
from utils.db import sesion
from database.models import Estadia, Huesped


class DialogoCargoExtra:
    """
    Diálogo para registrar un consumo adicional a la cuenta del huésped
    (restaurante, lavandería, minibar, etc.).

    Al confirmar crea la línea de cargo y ofrece aplicar saldo a favor
    del huésped si está disponible.
    """

    def __init__(self, pagina: ft.Page, estadia: Estadia, al_completar):
        self.pagina = pagina
        self.estadia = estadia
        self.al_completar = al_completar
        self.dialogo = None
        self._saldo_favor = 0.0
        self._cargo_total = 0.0
        self._titular = None

        with sesion() as db:
            if self.estadia.huespedes:
                self._titular = db.get(Huesped, self.estadia.huespedes[0].id)
                if self._titular:
                    self._saldo_favor = round(float(self._titular.credito_usd or 0), 2)

        self.campo_servicio = ft.TextField(
            label="Descripción del Servicio", expand=True
        )
        self.campo_cantidad = ft.TextField(
            label="Cant.",
            value="1",
            width=70,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.campo_monto = ft.TextField(
            label="Precio unitario (USD)",
            prefix_text="$ ",
            width=160,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.chip_saldo = ft.Container(visible=False)
        self._actualizar_chip_saldo()

    def _actualizar_chip_saldo(self):
        if self._saldo_favor > 0.01:
            self.chip_saldo = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET,
                                color=ft.Colors.GREEN_700, size=18),
                        ft.Text(
                            f"Saldo a favor disponible: ${self._saldo_favor:.2f}",
                            color=ft.Colors.GREEN_700,
                            size=13,
                        ),
                    ],
                    spacing=5,
                ),
                visible=True,
                padding=10,
                bgcolor=ft.Colors.GREEN_50,
                border_radius=8,
            )
        else:
            self.chip_saldo = ft.Container(visible=False)

    def _mostrar_dialogo_confirmacion(self, cargo_total: float):
        usar_saldo = self._saldo_favor > 0.01 and self._saldo_favor >= cargo_total
        parcial = 0 < self._saldo_favor < cargo_total

        if usar_saldo:
            texto = (
                f"El huésped tiene saldo a favor de ${self._saldo_favor:.2f}.\n"
                f"¿Desea aplicar el cargo de ${cargo_total:.2f} al saldo a favor?"
            )
            texto_confirmar = "Aplicar saldo a favor"
        elif parcial:
            texto = (
                f"El huésped tiene saldo a favor parcial de ${self._saldo_favor:.2f}.\n"
                f"El cargo es de ${cargo_total:.2f}. "
                f"Se aplicarán ${self._saldo_favor:.2f} del saldo y quedarán ${cargo_total - self._saldo_favor:.2f} pendientes."
            )
            texto_confirmar = "Aplicar parcialmente"
        else:
            self._confirmar_cargo()
            return

        dialogo_confirmacion = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirmar Cargo"),
            content=ft.Text(texto),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self.pagina.close(dialogo_confirmacion),
                ),
                ft.ElevatedButton(
                    texto_confirmar,
                    bgcolor=ft.Colors.GREEN_700,
                    color=ft.Colors.WHITE,
                    on_click=lambda _: self._procesar_con_saldo_favor(dialogo_confirmacion),
                ),
            ],
        )
        self.pagina.open(dialogo_confirmacion)

    def _procesar_con_saldo_favor(self, dialogo_padre):
        self.pagina.close(dialogo_padre)
        sesion = SesionLocal()
        try:
            cantidad = max(1, int(self.campo_cantidad.value or 1))
            nombre_concepto = (self.campo_servicio.value or "").strip() or "Consumo"
            config = leer_config_financiera(sesion)
            tasa = config.tasa_cambio

            monto_cargo = self._cargo_total
            monto_aplicar = min(self._saldo_favor, monto_cargo)
            monto_restante = monto_cargo - monto_aplicar

            hab_result = (
                sesion.query(Habitacion.numero)
                .filter(Habitacion.id == self.estadia.habitacion_id)
                .scalar()
            )
            hab_num = hab_result if hab_result else f"Hab#{self.estadia.habitacion_id}"

            titular_id = self.estadia.huespedes[0].id if self.estadia.huespedes else None
            titular = sesion.get(Huesped, titular_id) if titular_id else None
            
            origen_credito = getattr(titular, 'credito_origen', '') or '' if titular else ''
            es_vuelto = origen_credito == 'vuelto'

            if monto_aplicar > 0.01:
                linea = folio_engine.crear_cargo_extra(
                    sesion,
                    estadia_id=self.estadia.id,
                    concepto=f"{nombre_concepto} x{cantidad}",
                    cantidad=1,
                    precio_unitario_usd=D(str(monto_cargo)),
                    config=config,
                )

                if titular:
                    titular.credito_usd = D(
                        str(max(D("0"), D(str(titular.credito_usd or 0)) - D(str(monto_aplicar))))
                    )
                    titular.credito_origen = ""

                confirmado = monto_restante <= 0.01

                if es_vuelto:
                    etiqueta_origen = "vuelto a favor"
                    etiqueta_origen_full = f"vuelto a favor ${monto_aplicar:.2f}"
                else:
                    etiqueta_origen = "saldo a favor"
                    etiqueta_origen_full = f"saldo a favor ${monto_aplicar:.2f}"

                if confirmado:
                    folio_engine.cancelar_lineas(sesion, [linea.id])
                    concepto_bita = f"{nombre_concepto} x{cantidad} ({etiqueta_origen} ${monto_aplicar:.2f})"
                    metodo_bita = etiqueta_origen.title()
                else:
                    folio_engine.crear_saldo_pendiente(
                        sesion,
                        estadia_id=self.estadia.id,
                        monto_usd=D(str(monto_restante)),
                        concepto=f"Restante {nombre_concepto}",
                        config=config,
                    )
                    concepto_bita = f"{nombre_concepto} x{cantidad} ({etiqueta_origen} ${monto_aplicar:.2f})"
                    metodo_bita = etiqueta_origen_full.title()

                led.registrar_pago(
                    sesion,
                    estadia_id=self.estadia.id,
                    concepto=f"Cargo {nombre_concepto} cubierto con {etiqueta_origen}",
                    monto_usd=D(str(monto_aplicar)),
                    tasa=D(str(tasa)),
                    referencia=etiqueta_origen.title(),
                    pago_id=None,
                )

                bitacora_id = _bita(
                    sesion=sesion,
                    pagina=self.pagina,
                    tipo=_TE.CARGO_EXTRA,
                    habitacion=hab_num,
                    concepto=concepto_bita,
                    monto_usd=monto_cargo,
                    metodo_pago=metodo_bita,
                    confirmado=confirmado,
                )

                try:
                    from modules.notifications.formatter import desde_evento
                    from modules.notifications.dispatcher import enviar_texto, guardar_telegram_message_id

                    reply_to_msg_id = None
                    checkin_msg = (
                        sesion.query(BitacoraEvento)
                        .filter(
                            BitacoraEvento.tipo == _TE.CHECKIN,
                            BitacoraEvento.habitacion == hab_num,
                            BitacoraEvento.telegram_message_id.isnot(None),
                        )
                        .order_by(BitacoraEvento.id.desc())
                        .first()
                    )
                    if checkin_msg:
                        reply_to_msg_id = checkin_msg.telegram_message_id

                    evento_dict = {
                        "tipo": _TE.CARGO_EXTRA,
                        "habitacion": hab_num,
                        "concepto": concepto_bita,
                        "monto_usd": monto_cargo,
                        "confirmado": confirmado,
                        "recepcionista": (self.pagina.session.get("usuario_activo") or {}).get(
                            "nombre_completo", ""
                        ),
                    }

                    msg = desde_evento(evento_dict)

                    exito, msg_id = enviar_texto(
                        msg,
                        reply_to_message_id=reply_to_msg_id,
                    )

                    if exito and msg_id and bitacora_id:
                        guardar_telegram_message_id(bitacora_id, str(msg_id))

                except Exception as _e:
                    print(f"[CargoExtra] Error Telegram: {_e}")

                self.pagina.open(
                    ft.SnackBar(
                        ft.Text(
                            f"Cargo cubierto completamente con {etiqueta_origen}"
                            if confirmado
                            else f"{etiqueta_origen.title()} aplicado (${monto_aplicar:.2f}), quedan ${monto_restante:.2f} pendientes"
                        ),
                        bgcolor=ft.Colors.GREEN_700,
                    )
                )
            else:
                self._confirmar_cargo(sesion=sesion)
                return

            sesion.commit()
            self.pagina.close(self.dialogo)
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(
                ft.SnackBar(
                    ft.Text(f"Error al procesar: {error}"),
                    bgcolor=ft.Colors.RED_700,
                )
            )
        finally:
            sesion.close()

    def _confirmar_cargo(self, sesion=None):
        if sesion is None:
            sesion = SesionLocal()
            cerrar_sesion = True
        else:
            cerrar_sesion = False

        try:
            cantidad = max(1, int(self.campo_cantidad.value or 1))
            precio_u = float(self.campo_monto.value)
            nombre_concepto = self.campo_servicio.value.strip() or "Consumo"
            config = leer_config_financiera(sesion)

            linea = folio_engine.crear_cargo_extra(
                sesion,
                estadia_id=self.estadia.id,
                concepto=nombre_concepto,
                cantidad=cantidad,
                precio_unitario_usd=D(str(precio_u)),
                config=config,
            )

            hab_result = (
                sesion.query(Habitacion.numero)
                .filter(Habitacion.id == self.estadia.habitacion_id)
                .scalar()
            )
            hab_num = hab_result if hab_result else f"Hab#{self.estadia.habitacion_id}"

            _bita(
                sesion=sesion,
                pagina=self.pagina,
                tipo=_TE.CARGO_EXTRA,
                habitacion=hab_num,
                concepto=f"{nombre_concepto} x{cantidad}",
                monto_usd=float(linea.total_usd),
                metodo_pago="",
                confirmado=False,
            )

            if cerrar_sesion:
                sesion.commit()
                self.pagina.close(self.dialogo)
                if self.al_completar:
                    self.al_completar()
            else:
                return sesion

        except Exception as error:
            sesion.rollback()
            self.pagina.open(
                ft.SnackBar(
                    ft.Text(f"Error al guardar: {error}"),
                    bgcolor=ft.Colors.RED_700,
                )
            )
            return None
        finally:
            if cerrar_sesion:
                sesion.close()

    def guardar_cargo(self, evento):
        cantidad = max(1, int(self.campo_cantidad.value or 1))
        precio_u = float(self.campo_monto.value or 0)
        if precio_u <= 0:
            self.campo_monto.error_text = "Ingrese un monto válido"
            self.campo_monto.update()
            return

        self._cargo_total = cantidad * precio_u

        if self._saldo_favor > 0.01:
            self._mostrar_dialogo_confirmacion(self._cargo_total)
        else:
            self._confirmar_cargo()

    def mostrar(self):
        self.dialogo = ft.AlertDialog(
            title=ft.Text("Registrar Consumo Adicional"),
            content=ft.Column(
                [
                    self.campo_servicio,
                    ft.Row(
                        [self.campo_cantidad, self.campo_monto],
                        spacing=10,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    self.chip_saldo,
                ],
                tight=True,
                spacing=15,
            ),
            actions=[
                ft.TextButton(
                    "Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)
                ),
                ft.ElevatedButton(
                    "Confirmar",
                    on_click=self.guardar_cargo,
                    bgcolor=ft.Colors.BLUE,
                ),
            ],
        )
        self.pagina.open(self.dialogo)
