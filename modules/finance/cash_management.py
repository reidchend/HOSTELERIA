# modules/finance/cash_management.py

import flet as ft
from datetime import datetime
from database.connection import SesionLocal
from database.models import Caja, Configuracion


class PantallaGestionCaja(ft.Container):
    """
    Vista de administración de la caja y finanzas.
    Muestra los saldos actuales, permite actualizar la tasa de cambio
    y registrar ingresos o egresos manuales en la caja chica.
    """

    def __init__(self, pagina: ft.Page, estado_app: dict):
        super().__init__()
        self.pagina     = pagina
        self.estado_app = estado_app
        self.expand     = True
        self.padding    = 30
        self._iniciar_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # DATOS
    # ─────────────────────────────────────────────────────────────────────────

    def obtener_datos_caja(self):
        """Devuelve los registros de Caja y Configuracion de la BD."""
        sesion = SesionLocal()
        try:
            caja = sesion.query(Caja).first()
            tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            return caja, tasa
        except Exception as error:
            print(f"❌ Error al obtener datos financieros: {error}")
            return None, None
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES
    # ─────────────────────────────────────────────────────────────────────────

    def actualizar_tasa(self, nuevo_valor: str):
        """Persiste la nueva tasa de cambio y actualiza el estado global de la app."""
        try:
            tasa_float = float(nuevo_valor)
            sesion = SesionLocal()
            config_tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            if config_tasa:
                config_tasa.valor = str(tasa_float)
                sesion.commit()
                self.estado_app["exchange_rate"] = tasa_float
                self.pagina.open(ft.SnackBar(
                    ft.Text(f"Tasa actualizada a {tasa_float:.2f} Bs."),
                    bgcolor=ft.Colors.GREEN_700,
                ))
            sesion.close()
            self.refrescar_ui()
        except ValueError:
            self.pagina.open(ft.SnackBar(
                ft.Text("Por favor ingrese un número válido"),
                bgcolor=ft.Colors.RED_700,
            ))

    def registrar_movimiento_caja(self, es_ingreso: bool):
        """Abre un diálogo para registrar un ingreso o egreso manual en la caja chica."""
        titulo     = "Nuevo Ingreso" if es_ingreso else "Nuevo Egreso / Gasto"
        color_btn  = ft.Colors.GREEN if es_ingreso else ft.Colors.RED

        campo_monto    = ft.TextField(
            label="Monto", prefix_text="$ ",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        campo_concepto = ft.TextField(label="Concepto / Motivo", multiline=True)
        selector_moneda = ft.Dropdown(
            label="Moneda",
            options=[
                ft.dropdown.Option("USD", "Dólares ($)"),
                ft.dropdown.Option("BS",  "Bolívares (Bs)"),
            ],
            value="USD",
        )

        def guardar_movimiento(evento):
            if not campo_monto.value or float(campo_monto.value) <= 0:
                campo_monto.error_text = "Monto requerido"
                campo_monto.update()
                return

            sesion = SesionLocal()
            try:
                caja   = sesion.query(Caja).first()
                monto  = float(campo_monto.value)

                if selector_moneda.value == "USD":
                    if es_ingreso:
                        caja.caja_chica_usd += monto
                    else:
                        if caja.caja_chica_usd < monto:
                            self.pagina.open(ft.SnackBar(ft.Text("Saldo USD insuficiente")))
                            return
                        caja.caja_chica_usd -= monto
                else:
                    if es_ingreso:
                        caja.caja_chica_bs += monto
                    else:
                        if caja.caja_chica_bs < monto:
                            self.pagina.open(ft.SnackBar(ft.Text("Saldo Bs insuficiente")))
                            return
                        caja.caja_chica_bs -= monto

                caja.ultima_actualizacion = datetime.now()
                sesion.commit()
                self.pagina.close(dialogo_movimiento)
                self.pagina.open(ft.SnackBar(
                    ft.Text("Movimiento registrado correctamente"),
                    bgcolor=ft.Colors.GREEN_800,
                ))
                self.refrescar_ui()
            except Exception as error:
                print(f"❌ Error en movimiento de caja: {error}")
            finally:
                sesion.close()

        dialogo_movimiento = ft.AlertDialog(
            title=ft.Text(titulo, color=color_btn),
            content=ft.Column([
                ft.Text("Complete los datos del movimiento:"),
                campo_monto,
                selector_moneda,
                campo_concepto,
            ], tight=True, spacing=15),
            actions=[
                ft.TextButton("Cancelar",  on_click=lambda _: self.pagina.close(dialogo_movimiento)),
                ft.ElevatedButton(
                    "Guardar",
                    bgcolor=color_btn, color=ft.Colors.WHITE,
                    on_click=guardar_movimiento,
                ),
            ],
        )
        self.pagina.open(dialogo_movimiento)

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DE UI
    # ─────────────────────────────────────────────────────────────────────────

    def _iniciar_ui(self):
        """Construye el árbol de widgets completo de la vista de caja."""
        caja, tasa = self.obtener_datos_caja()

        if not caja:
            self.content = ft.Text("No se pudo cargar la información de la caja.")
            return

        self.campo_tasa = ft.TextField(
            label="Tasa USD/Bs", value=tasa.valor if tasa else "0.00",
            width=150, suffix_text="Bs",
            text_align=ft.TextAlign.RIGHT,
            border_color=ft.Colors.BLUE_400,
        )

        self.tarjeta_usd = self.crear_tarjeta_saldo(
            "Saldo Dólares", f"$ {caja.caja_chica_usd:.2f}",
            ft.Colors.GREEN_700, ft.Icons.ATTACH_MONEY,
        )
        self.tarjeta_bs = self.crear_tarjeta_saldo(
            "Saldo Bolívares", f"Bs {caja.caja_chica_bs:.2f}",
            ft.Colors.BLUE_700, ft.Icons.MONEY,
        )

        self.content = ft.Column([
            ft.Text("Gestión de Caja y Finanzas", size=32, weight="bold",
                    color=ft.Colors.BLUE_900),
            ft.Text("Administra la tasa de cambio y movimientos de la caja chica",
                    size=14, color=ft.Colors.GREY_600),
            ft.Container(height=20),

            # Fila de saldos y tasa
            ft.Row([
                self.tarjeta_usd,
                self.tarjeta_bs,
                ft.Container(
                    content=ft.Column([
                        ft.Text("Tasa del Día", weight="bold", color=ft.Colors.WHITE),
                        self.campo_tasa,
                        ft.ElevatedButton(
                            "Actualizar Tasa",
                            icon=ft.Icons.REFRESH,
                            on_click=lambda _: self.actualizar_tasa(self.campo_tasa.value),
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
                            ),
                        ),
                    ], spacing=10),
                    padding=20, bgcolor=ft.Colors.BLUE_GREY_800,
                    border_radius=15, width=250, height=180,
                ),
            ], alignment=ft.MainAxisAlignment.START, spacing=25),

            ft.Divider(height=40),
            ft.Text("Operaciones de Caja Chica", size=18, weight="bold"),

            # Botones de ingreso / egreso
            ft.Row([
                ft.ElevatedButton(
                    "Ingreso Manual",
                    icon=ft.Icons.ADD_CIRCLE,
                    bgcolor=ft.Colors.GREEN_50, color=ft.Colors.GREEN_900,
                    height=50,
                    on_click=lambda _: self.registrar_movimiento_caja(es_ingreso=True),
                ),
                ft.ElevatedButton(
                    "Salida / Gasto",
                    icon=ft.Icons.REMOVE_CIRCLE,
                    bgcolor=ft.Colors.RED_50, color=ft.Colors.RED_900,
                    height=50,
                    on_click=lambda _: self.registrar_movimiento_caja(es_ingreso=False),
                ),
            ], spacing=20),
        ], scroll=ft.ScrollMode.AUTO, expand=True)

    def crear_tarjeta_saldo(self, titulo: str, monto: str, color, icono) -> ft.Container:
        """Crea una tarjeta de saldo con ícono y valor destacado."""
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(icono, size=24, color=color),
                    ft.Text(titulo, size=14, color=ft.Colors.GREY_700, weight="w500"),
                ], alignment=ft.MainAxisAlignment.START, spacing=10),
                ft.Text(monto, size=30, weight="bold", color=color),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=15),
            width=280, height=180,
            bgcolor=ft.Colors.WHITE,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=15, padding=25,
            shadow=ft.BoxShadow(
                blur_radius=15,
                color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                offset=ft.Offset(0, 5),
            ),
        )

    def refrescar_ui(self):
        """Recarga los datos desde la BD y actualiza solo los valores mostrados."""
        caja, tasa = self.obtener_datos_caja()
        if caja and tasa:
            self.tarjeta_usd.content.controls[1].value = f"$ {caja.caja_chica_usd:.2f}"
            self.tarjeta_bs.content.controls[1].value  = f"Bs {caja.caja_chica_bs:.2f}"
            self.campo_tasa.value = tasa.valor
            self.update()
            self.pagina.update()