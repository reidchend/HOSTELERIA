# modules/finance/extra_charges.py

import flet as ft
from database.connection import SesionLocal
from database.models import CargoExtra, Estadia, LineaCuenta, TipoLinea, Pago, MetodoPago


class DialogoCargoExtra:
    """
    Diálogo para registrar un consumo adicional a la cuenta del huésped
    (restaurante, lavandería, minibar, etc.).

    Al confirmar crea DOS registros en la BD:
      - CargoExtra: para mantener compatibilidad con el modelo existente.
      - LineaCuenta: la línea que aparece en el historial de cuenta y puede
                     seleccionarse para cobrar desde details.py.
    """

    def __init__(self, pagina: ft.Page, estadia: Estadia, al_completar):
        self.pagina       = pagina
        self.estadia      = estadia
        self.al_completar = al_completar
        self.dialogo      = None

        self.campo_servicio  = ft.TextField(label="Descripción del Servicio", expand=True)
        self.campo_cantidad  = ft.TextField(
            label="Cant.", value="1", width=70,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.campo_monto     = ft.TextField(
            label="Precio unitario (USD)", prefix_text="$ ", width=160,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        saldo_disponible = getattr(estadia, "deposito_usd", 0.0)
        self.texto_saldo = ft.Text(
            f"Saldo a favor: ${saldo_disponible:.2f}",
            color=ft.Colors.GREEN_700 if saldo_disponible > 0 else ft.Colors.RED_400,
            weight="bold",
        )
        self.interruptor_saldo = ft.Switch(
            label="Saldar directamente con saldo a favor",
            value=False,
            disabled=saldo_disponible <= 0,
        )

    def guardar_cargo(self, evento):
        sesion = SesionLocal()
        try:
            cantidad = max(1, int(self.campo_cantidad.value or 1))
            precio_u = float(self.campo_monto.value)
            if precio_u <= 0:
                self.campo_monto.error_text = "Ingrese un monto válido"
                self.campo_monto.update()
                return

            # El recepcionista ingresa el monto final ya con IVA incluido.
            # No se aplica ningún cálculo adicional.
            monto_total = round(cantidad * precio_u, 2)
            monto_base  = monto_total  # se guarda el mismo valor en CargoExtra


            nombre_concepto = self.campo_servicio.value.strip() or "Consumo"
            if self.interruptor_saldo.value:
                nombre_concepto += " (Saldado con saldo a favor)"

            # 1. CargoExtra (compatibilidad con el modelo existente)
            nuevo_cargo = CargoExtra(
                estadia_id      = self.estadia.id,
                nombre_servicio = nombre_concepto,
                monto_usd       = monto_base,
                cantidad        = cantidad,
            )
            sesion.add(nuevo_cargo)
            sesion.flush()   # obtener ID para asociarlo a la línea si se cancela ya

            # 2. LineaCuenta para el historial de cuenta abierta
            cancelada_ya = False
            if self.interruptor_saldo.value:
                estadia_bd = sesion.get(Estadia, self.estadia.id)
                if estadia_bd.deposito_usd >= monto_total:
                    estadia_bd.deposito_usd -= monto_total
                    cancelada_ya = True
                    # Registro contable: salida de saldo a favor
                    sesion.add(Pago(
                        estadia_id    = self.estadia.id,
                        monto_usd     = monto_total,
                        monto_bs      = a_bs(monto_total, config.tasa_cambio),
                        tasa_cambio   = config.tasa_cambio,
                        metodo        = MetodoPago.SALDO_FAVOR,
                        referencia    = "—",
                        descripcion   = f"Cargo saldado con saldo a favor: {nombre_concepto}",
                        es_devolucion = False,
                        creado_en     = datetime.now(),
                    ))
                else:
                    self.pagina.open(ft.SnackBar(
                        ft.Text("Saldo a favor insuficiente para cubrir el cargo"),
                        bgcolor=ft.Colors.ORANGE_700,
                    ))
                    sesion.rollback()
                    return

            sesion.add(LineaCuenta(
                estadia_id = self.estadia.id,
                tipo       = TipoLinea.CARGO_EXTRA,
                concepto   = (
                    f"{nombre_concepto} x{cantidad}"
                    if cantidad > 1 else nombre_concepto
                ),
                monto_usd  = monto_total,
                cancelada  = cancelada_ya,
            ))

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
        self.dialogo = ft.AlertDialog(
            title=ft.Text("Registrar Consumo Adicional"),
            content=ft.Column([
                self.campo_servicio,
                ft.Row([self.campo_cantidad, self.campo_monto, self.texto_saldo],
                       spacing=10, alignment=ft.MainAxisAlignment.START),
                ft.Divider(),
                self.interruptor_saldo,
            ], tight=True, spacing=15),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(self.dialogo)),
                ft.ElevatedButton(
                    "Confirmar", on_click=self.guardar_cargo,
                    bgcolor=ft.Colors.BLUE,
                ),
            ],
        )
        self.pagina.open(self.dialogo)