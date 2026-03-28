# modules/finance/extra_charges.py

import flet as ft
from database.connection import SesionLocal
from database.models import Estadia, Habitacion
from modules.finance.engine import folio as folio_engine
from modules.finance.bitacora import registrar as _bita
from database.models import TipoEvento as _TE
from utils.calculos_financieros import leer_config_financiera


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
        self.pagina = pagina
        self.estadia = estadia
        self.al_completar = al_completar
        self.dialogo = None

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

        # Saldo a favor se gestiona en el Check-Out; no en cargos extras

    def guardar_cargo(self, evento):
        sesion = SesionLocal()
        try:
            cantidad = max(1, int(self.campo_cantidad.value or 1))
            precio_u = float(self.campo_monto.value)
            if precio_u <= 0:
                self.campo_monto.error_text = "Ingrese un monto válido"
                self.campo_monto.update()
                return

            nombre_concepto = self.campo_servicio.value.strip() or "Consumo"
            config = leer_config_financiera(sesion)

            # FolioEngine crea la línea y registra el CARGO en el ledger
            from decimal import Decimal

            linea = folio_engine.crear_cargo_extra(
                sesion,
                estadia_id=self.estadia.id,
                concepto=nombre_concepto,
                cantidad=cantidad,
                precio_unitario_usd=Decimal(str(precio_u)),
                config=config,
            )

            # Obtener número de habitación directamente de la BD
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
                concepto=f"Cargo extra — {nombre_concepto} x{cantidad} (pendiente por cancelar)",
                monto_usd=float(linea.total_usd),
                metodo_pago="",
                confirmado=False,
            )

            sesion.commit()
            self.pagina.close(self.dialogo)
            if self.al_completar:
                self.al_completar()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(
                ft.SnackBar(
                    ft.Text(f"Error al guardar: {error}"),
                    bgcolor=ft.Colors.RED_700,
                )
            )
        finally:
            sesion.close()

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
