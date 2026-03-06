# modules/finance/shift_closing.py

import flet as ft
from datetime import datetime
from database.connection import SesionLocal
from database.models import Turno, Pago, Caja


class DialogoCierreTurno:
    """
    Diálogo de cierre de turno.
    Muestra el resumen calculado por el sistema (ventas netas y fondo de caja chica),
    pide el conteo físico del recepcionista y registra las diferencias al cerrar.
    """

    def __init__(self, pagina: ft.Page, id_turno: int, al_cerrar_turno):
        self.pagina         = pagina
        self.id_turno       = id_turno
        self.al_cerrar_turno = al_cerrar_turno
        self.dialogo        = None

        # Calcular los saldos esperados por el sistema antes de construir la UI
        self.resumen = self.calcular_saldos_sistema()

        # Campos de conteo físico
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

        # Etiquetas de diferencia (se actualizan mientras escribe)
        self.texto_diferencia_principal = ft.Text("Diferencia: $ 0.00", color=ft.Colors.GREY)
        self.texto_diferencia_chica     = ft.Text("Diferencia: $ 0.00", color=ft.Colors.GREY)

    # ─────────────────────────────────────────────────────────────────────────
    # CÁLCULO DEL SISTEMA
    # ─────────────────────────────────────────────────────────────────────────

    def calcular_saldos_sistema(self) -> dict:
        """
        Suma todos los pagos cobrados durante el turno y los vueltos entregados
        para calcular lo que el sistema espera encontrar en cada caja.
        """
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

            ingresos_usd     = sum(p.monto_usd for p in cobros)
            salidas_principal = sum(r.monto_usd for r in devoluciones_principal)
            salidas_chica     = sum(r.monto_usd for r in devoluciones_chica)

            return {
                "esperado_principal": ingresos_usd - salidas_principal,
                "esperado_chica":     turno.inicial_usd - salidas_chica,
            }
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # REVISIÓN EN TIEMPO REAL
    # ─────────────────────────────────────────────────────────────────────────

    def revisar_diferencias(self, evento):
        """Compara el conteo físico ingresado con el saldo esperado del sistema."""
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
        Marca el turno como cerrado, registra el conteo real del recepcionista
        y pone la caja principal en $0 (el dinero se entrega a administración).
        """
        sesion = SesionLocal()
        try:
            turno = sesion.get(Turno, self.id_turno)
            turno.hora_fin     = datetime.now()
            turno.usd_esperado = self.resumen["esperado_principal"]
            turno.usd_real     = float(self.campo_principal_usd.value)
            turno.activo       = False

            # La caja principal queda en $0 tras la entrega a administración.
            # La caja chica mantiene el conteo físico para el siguiente turno.
            caja = sesion.query(Caja).first()
            caja.saldo_principal_usd  = 0.0
            caja.caja_chica_usd       = float(self.campo_chica_usd.value)
            caja.ultima_actualizacion = datetime.now()

            sesion.commit()
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
        """Construye y abre el diálogo de cierre de turno."""
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