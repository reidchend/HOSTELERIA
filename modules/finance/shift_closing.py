# modules/finance/shift_closing.py

import flet as ft
from datetime import datetime
from database.connection import SesionLocal
from database.models import Turno, Pago, Caja


class DialogoCierreTurno:
    """
    Diálogo de cierre de turno.
    Muestra el resumen calculado por el sistema, pide el conteo físico
    y registra las diferencias al cerrar.
    Envía notificación completa a Telegram automáticamente.
    """

    def __init__(self, pagina: ft.Page, id_turno: int, al_cerrar_turno):
        self.pagina          = pagina
        self.id_turno        = id_turno
        self.al_cerrar_turno = al_cerrar_turno
        self.dialogo         = None
        self._recepcionista  = ""

        # Leer nombre del recepcionista desde la sesión
        try:
            usuario = pagina.session.get("usuario_activo") or {}
            self._recepcionista = usuario.get("nombre_completo", "")
        except Exception:
            pass

        # Calcular los saldos esperados
        self.resumen = self.calcular_saldos_sistema()

        self.campo_principal_usd = ft.TextField(
            label="Monto Físico Caja Principal ($)",
            prefix_text="$ ", value="0",
            on_change=self.revisar_diferencias,
        )
        self.campo_chica_usd = ft.TextField(
            label="Monto Físico Caja Chica ($)",
            prefix_text="$ ", value="0",
            on_change=self.revisar_diferencias,
        )

        self.texto_diferencia_principal = ft.Text("Diferencia: $ 0.00", color=ft.Colors.GREY)
        self.texto_diferencia_chica     = ft.Text("Diferencia: $ 0.00", color=ft.Colors.GREY)

    # ─────────────────────────────────────────────────────────────────────────
    # CÁLCULO DEL SISTEMA
    # ─────────────────────────────────────────────────────────────────────────

    def calcular_saldos_sistema(self) -> dict:
        sesion = SesionLocal()
        try:
            turno = sesion.get(Turno, self.id_turno)

            cobros = sesion.query(Pago).filter(
                Pago.creado_en >= turno.hora_inicio,
                Pago.es_devolucion == False,
            ).all()

            devoluciones_principal = sesion.query(Pago).filter(
                Pago.creado_en >= turno.hora_inicio,
                Pago.es_devolucion == True,
                Pago.descripcion.contains("principal"),
            ).all()

            devoluciones_chica = sesion.query(Pago).filter(
                Pago.creado_en >= turno.hora_inicio,
                Pago.es_devolucion == True,
                Pago.descripcion.contains("chica"),
            ).all()

            ingresos_usd       = float(sum(p.monto_usd for p in cobros))
            vueltos_usd        = float(sum(p.monto_usd for p in (devoluciones_principal + devoluciones_chica)))
            salidas_principal  = float(sum(r.monto_usd for r in devoluciones_principal))
            salidas_chica      = float(sum(r.monto_usd for r in devoluciones_chica))

            return {
                "esperado_principal": ingresos_usd - salidas_principal,
                "esperado_chica":     float(turno.inicial_usd) - salidas_chica,
                "total_cobrado":      ingresos_usd,
                "total_vueltos":      vueltos_usd,
                "neto":               ingresos_usd - vueltos_usd,
            }
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # REVISIÓN EN TIEMPO REAL
    # ─────────────────────────────────────────────────────────────────────────

    def revisar_diferencias(self, evento):
        try:
            fisico_principal = float(self.campo_principal_usd.value or 0)
            fisico_chica     = float(self.campo_chica_usd.value     or 0)

            diff_principal = fisico_principal - self.resumen["esperado_principal"]
            diff_chica     = fisico_chica     - self.resumen["esperado_chica"]

            self.texto_diferencia_principal.value = f"Diferencia: $ {diff_principal:.2f}"
            self.texto_diferencia_principal.color = (
                ft.Colors.RED_700 if diff_principal < 0 else ft.Colors.GREEN_700
            )
            self.texto_diferencia_chica.value = f"Diferencia: $ {diff_chica:.2f}"
            self.texto_diferencia_chica.color = (
                ft.Colors.RED_700 if diff_chica < 0 else ft.Colors.GREEN_700
            )
            self.pagina.update()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # CIERRE DEL TURNO
    # ─────────────────────────────────────────────────────────────────────────

    def finalizar_turno(self, evento):
        """
        Marca el turno como cerrado y envía el resumen a Telegram.
        """
        sesion = SesionLocal()
        try:
            fisico_principal = float(self.campo_principal_usd.value or 0)
            fisico_chica     = float(self.campo_chica_usd.value     or 0)
            diferencia       = fisico_principal - self.resumen["esperado_principal"]

            turno = sesion.get(Turno, self.id_turno)
            turno.hora_fin     = datetime.now()
            turno.usd_esperado = self.resumen["esperado_principal"]
            turno.usd_real     = fisico_principal
            turno.activo       = False

            caja = sesion.query(Caja).first()
            caja.saldo_principal_usd  = 0.0
            caja.caja_chica_usd       = fisico_chica
            caja.ultima_actualizacion = datetime.now()

            sesion.commit()

            # ── Notificación Telegram de cierre de turno ──────────────────────
            try:
                from modules.notifications.dispatcher import enviar_cierre_turno
                enviar_cierre_turno(
                    recepcionista  = self._recepcionista,
                    cobrado_usd    = self.resumen["total_cobrado"],
                    vueltos_usd    = self.resumen["total_vueltos"],
                    neto_usd       = self.resumen["neto"],
                    caja_chica_usd = fisico_chica,
                    diferencia_usd = diferencia,
                )
            except Exception as e:
                print(f"[CierreTurno] Error al notificar Telegram: {e}")

            self.pagina.close(self.dialogo)
            if self.al_cerrar_turno:
                self.al_cerrar_turno()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error al cerrar el turno: {error}"),
                bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DEL DIÁLOGO
    # ─────────────────────────────────────────────────────────────────────────

    def mostrar(self):
        self.dialogo = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.LOCK),
                ft.Text("Cierre de Turno"),
            ]),
            content=ft.Container(
                width=450,
                content=ft.Column([
                    ft.Text("Resumen del Sistema", weight="bold"),
                    ft.ListTile(
                        title=ft.Text(
                            f"Ventas a Entregar: $ {self.resumen['esperado_principal']:.2f}"
                        ),
                        subtitle=ft.Text("Caja Principal (Ventas Netas)"),
                        leading=ft.Icon(ft.Icons.MONETIZATION_ON, color=ft.Colors.GREEN),
                    ),
                    ft.ListTile(
                        title=ft.Text(
                            f"Fondo en Caja Chica: $ {self.resumen['esperado_chica']:.2f}"
                        ),
                        subtitle=ft.Text("Debe permanecer en el hotel"),
                        leading=ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.BLUE),
                    ),
                    ft.Divider(),
                    ft.Text("Conteo Físico en Efectivo", weight="bold"),
                    self.campo_principal_usd,
                    self.texto_diferencia_principal,
                    self.campo_chica_usd,
                    self.texto_diferencia_chica,
                ], tight=True, spacing=10),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                ft.ElevatedButton(
                    "Cerrar Turno y Salir",
                    icon=ft.Icons.SAVE_ALT,
                    bgcolor=ft.Colors.RED_800, color=ft.Colors.WHITE,
                    on_click=self.finalizar_turno,
                ),
            ],
        )
        self.pagina.open(self.dialogo)