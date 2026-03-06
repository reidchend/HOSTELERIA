# modules/finance/extra_charges.py

import flet as ft
from database.connection import SesionLocal
from database.models import CargoExtra, Estadia


class DialogoCargoExtra:
    """
    Diálogo para registrar un consumo adicional a la cuenta del huésped
    (servicio de lavandería, restaurante, minibar, etc.).
    Si la estadía tiene saldo a favor, ofrece saldar el cargo directamente.
    """

    def __init__(self, pagina: ft.Page, estadia: Estadia, al_completar):
        self.pagina       = pagina
        self.estadia      = estadia
        self.al_completar = al_completar
        self.dialogo      = None

        # Campos del formulario
        self.campo_servicio = ft.TextField(label="Descripción del Servicio", expand=True)
        self.campo_monto    = ft.TextField(
            label="Monto (USD)", prefix_text="$ ", width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        # Indicador del saldo a favor disponible en la estadía
        saldo_disponible = getattr(estadia, 'deposito_usd', 0.0)
        self.texto_saldo = ft.Text(
            f"Saldo a favor: $ {saldo_disponible:.2f}",
            color=ft.Colors.GREEN_700 if saldo_disponible > 0 else ft.Colors.RED_400,
            weight="bold",
        )
        self.interruptor_saldo = ft.Switch(
            label="Saldar con saldo a favor",
            value=saldo_disponible > 0,
            disabled=saldo_disponible <= 0,
        )

    def guardar_cargo(self, evento):
        """Crea el cargo extra y, si se eligió, descuenta del saldo de la estadía."""
        sesion = SesionLocal()
        try:
            monto = float(self.campo_monto.value)

            nombre_servicio = self.campo_servicio.value
            if self.interruptor_saldo.value:
                nombre_servicio += " (Saldado con saldo a favor)"

            # 1. Crear el cargo
            nuevo_cargo = CargoExtra(
                estadia_id      = self.estadia.id,
                nombre_servicio = nombre_servicio,
                monto_usd       = monto,
            )
            sesion.add(nuevo_cargo)

            # 2. Si se eligió usar el saldo a favor, descontar de la estadía
            if self.interruptor_saldo.value:
                estadia_bd = sesion.get(Estadia, self.estadia.id)
                if estadia_bd.deposito_usd >= monto:
                    estadia_bd.deposito_usd -= monto
                else:
                    self.pagina.open(ft.SnackBar(
                        ft.Text("Saldo a favor insuficiente para cubrir el monto"),
                        bgcolor=ft.Colors.ORANGE_700,
                    ))
                    return

            sesion.commit()
            self.pagina.close(self.dialogo)
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error al guardar: {error}"),
                bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()

    def mostrar(self):
        """Construye y abre el diálogo de cargo extra."""
        self.dialogo = ft.AlertDialog(
            title=ft.Text("Registrar Consumo Adicional"),
            content=ft.Column([
                self.campo_servicio,
                ft.Row(
                    [self.campo_monto, self.texto_saldo],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Divider(),
                self.interruptor_saldo,
            ], tight=True, spacing=15),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                ft.ElevatedButton(
                    "Confirmar", on_click=self.guardar_cargo,
                    bgcolor=ft.Colors.BLUE,
                ),
            ],
        )
        self.pagina.open(self.dialogo)