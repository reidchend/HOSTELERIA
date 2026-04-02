# modules/finance/cash_opening.py

import flet as ft
from datetime import datetime
from database.connection import SesionLocal
from database.models import Caja, Configuracion, Turno, TipoEvento
from modules.finance.bitacora import registrar as _bita
from utils import handle_error


class DialogoAperturaTurno:
    """
    Diálogo de apertura de turno.

    Telegram:
      · Apertura de turno  → SIEMPRE se envía al abrir un turno nuevo.
      · Movimiento de caja → SOLO si el monto de caja chica cambió
                             respecto al valor anterior en BD.
    """

    def __init__(self, pagina: ft.Page, usuario: dict, al_completar):
        self.pagina       = pagina
        self.usuario      = usuario
        self.al_completar = al_completar
        self.dialogo      = None

        sesion = SesionLocal()
        try:
            caja = sesion.query(Caja).first()
            config_tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            self.tasa_actual = float(config_tasa.valor) if config_tasa else 0.0

            # Valores anteriores para detectar cambios en caja chica
            self._usd_anterior = float(caja.caja_chica_usd or 0) if caja else 0.0
            self._bs_anterior  = float(caja.caja_chica_bs  or 0) if caja else 0.0

            self.turno_existente = sesion.query(Turno).filter(
                Turno.usuario_id == usuario["id"],
                Turno.activo == True,
            ).order_by(Turno.hora_inicio.desc()).first()

            if self.turno_existente:
                self.tasa_actual = self.turno_existente.tasa_inicial
        finally:
            sesion.close()

        self.campo_usd = ft.TextField(
            label="Efectivo USD en Caja",
            value=f"{self._usd_anterior:.2f}",
            prefix_text="$ ", expand=True,
        )
        self.campo_bs = ft.TextField(
            label="Efectivo Bs en Caja",
            value=f"{self._bs_anterior:.2f}",
            prefix_text="Bs ", expand=True,
        )
        self.campo_tasa = ft.TextField(
            label="Tasa de Cambio de Hoy",
            value=f"{self.tasa_actual:.2f}",
            expand=True,
        )

    def confirmar_apertura(self, evento):
        sesion = SesionLocal()
        try:
            usd_fisico     = float(self.campo_usd.value)
            bs_fisico      = float(self.campo_bs.value)
            tasa_ingresada = float(self.campo_tasa.value)

            # 1. Crear registro del turno
            nuevo_turno = Turno(
                usuario_id   = self.usuario['id'],
                hora_inicio  = datetime.now(),
                inicial_usd  = usd_fisico,
                inicial_bs   = bs_fisico,
                tasa_inicial = tasa_ingresada,
                activo       = True,
            )
            sesion.add(nuevo_turno)

            # 2. Actualizar tasa global
            config_tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            if config_tasa:
                config_tasa.valor = str(tasa_ingresada)

            # 3. Sincronizar caja chica
            caja_bd = sesion.query(Caja).first()
            if caja_bd:
                caja_bd.caja_chica_usd       = usd_fisico
                caja_bd.caja_chica_bs        = bs_fisico
                caja_bd.ultima_actualizacion = datetime.now()

            # 4. Bitácora — sin notificación Telegram (se gestiona manualmente abajo)
            _bita(
                sesion             = sesion,
                pagina             = self.pagina,
                tipo               = TipoEvento.CAJA,
                concepto           = (
                    f"Apertura de turno — Caja chica: ${usd_fisico:.2f} / "
                    f"Bs. {bs_fisico:,.2f} · Tasa: {tasa_ingresada:.2f}"
                ),
                monto_usd          = usd_fisico,
                monto_bs           = bs_fisico,
                recepcionista      = self.usuario.get('nombre_completo', ''),
                notificar_telegram = False,
            )

            sesion.commit()

            self.pagina.session.set("id_turno_actual", nuevo_turno.id)
            self.pagina.session.set("tasa_cambio",     tasa_ingresada)

            # ── Notificaciones Telegram ───────────────────────────────────────

            from modules.notifications.dispatcher import (
                enviar_apertura_turno,
                enviar_texto,
            )
            from modules.notifications import formatter as fmt

            # A) Apertura de turno — SIEMPRE
            enviar_apertura_turno(
                recepcionista = self.usuario.get('nombre_completo', ''),
                caja_usd      = usd_fisico,
                caja_bs       = bs_fisico,
                tasa          = tasa_ingresada,
            )

            # B) Movimiento de caja chica — SOLO si hubo cambio
            usd_cambio = abs(usd_fisico - self._usd_anterior) > 0.01
            bs_cambio  = abs(bs_fisico  - self._bs_anterior)  > 0.01

            if usd_cambio or bs_cambio:
                enviar_texto(fmt.desde_evento({
                    "tipo":          TipoEvento.CAJA,
                    "habitacion":    "",
                    "concepto":      (
                        f"Ajuste de caja chica al abrir turno — "
                        f"USD: {self._usd_anterior:.2f} → {usd_fisico:.2f}  |  "
                        f"Bs: {self._bs_anterior:,.2f} → {bs_fisico:,.2f}"
                    ),
                    "monto_usd":     usd_fisico,
                    "monto_bs":      bs_fisico,
                    "metodo_pago":   "",
                    "referencia":    "",
                    "recepcionista": self.usuario.get('nombre_completo', ''),
                    "confirmado":    True,
                }, tasa=tasa_ingresada))
                print(
                    f"[AperturaTurno] Movimiento de caja enviado — "
                    f"USD: {self._usd_anterior:.2f}→{usd_fisico:.2f}  "
                    f"Bs: {self._bs_anterior:.2f}→{bs_fisico:.2f}"
                )
            else:
                print("[AperturaTurno] Sin cambios en caja chica — movimiento omitido.")

            self.pagina.close(self.dialogo)
            self.al_completar(tasa_ingresada)
            self.pagina.open(ft.SnackBar(
                ft.Text("Turno abierto y caja sincronizada"),
                bgcolor=ft.Colors.GREEN_700,
            ))

        except ValueError:
            self.pagina.open(ft.SnackBar(
                ft.Text("Error: Ingrese montos numéricos válidos"),
                bgcolor=ft.Colors.RED_700,
            ))
        except Exception as error:
            sesion.rollback()
            handle_error(error, self.pagina, "Apertura turno")
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error al abrir turno: {error}"),
                bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()

    def mostrar(self):
        if self.turno_existente:
            self.pagina.session.set("id_turno_actual", self.turno_existente.id)
            self.pagina.session.set("tasa_cambio",     self.tasa_actual)
            self.pagina.open(ft.SnackBar(
                ft.Text(
                    f"Turno del {self.turno_existente.hora_inicio.strftime('%d/%m/%Y %H:%M')} "
                    f"retomado — Tasa Bs. {self.tasa_actual:.2f}",
                    color=ft.Colors.WHITE,
                ),
                bgcolor=ft.Colors.BLUE_700,
                duration=4000,
            ))
            self.al_completar(self.tasa_actual)
            return

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.LOCK_OPEN),
                ft.Text("Apertura de Turno"),
            ]),
            content=ft.Container(
                width=400,
                content=ft.Column([
                    ft.Text(
                        f"Bienvenido/a, {self.usuario['nombre_completo']}",
                        weight="bold", size=18,
                    ),
                    ft.Text(
                        "Verifique los montos en físico antes de iniciar:",
                        color=ft.Colors.GREY_700,
                    ),
                    ft.Divider(),
                    ft.Row([self.campo_usd, self.campo_bs]),
                    self.campo_tasa,
                    ft.Text(
                        "Al confirmar se registrará el inicio de su jornada.",
                        size=12, italic=True, color=ft.Colors.BLUE_GREY_400,
                    ),
                ], tight=True, spacing=15),
            ),
            actions=[
                ft.ElevatedButton(
                    "Confirmar y Entrar",
                    icon=ft.Icons.CHECK,
                    on_click=self.confirmar_apertura,
                    bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
                ),
            ],
        )
        self.pagina.open(self.dialogo)