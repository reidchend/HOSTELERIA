# modules/finance/cash_opening.py

import flet as ft
from datetime import datetime
from database.connection import SesionLocal
from database.models import Caja, Configuracion, Turno


class DialogoAperturaTurno:
    """
    Diálogo de apertura de turno.
    El recepcionista cuenta el efectivo físico e ingresa la tasa del día.
    Al confirmar, se crea el registro del turno y se sincroniza la caja.
    """

    def __init__(self, pagina: ft.Page, usuario: dict, al_completar):
        self.pagina       = pagina
        self.usuario      = usuario
        self.al_completar = al_completar
        self.dialogo      = None

        # Cargar datos actuales de la caja y la tasa
        sesion = SesionLocal()
        try:
            caja = sesion.query(Caja).first()
            config_tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            self.tasa_actual = float(config_tasa.valor) if config_tasa else 0.0
            saldo_chica_usd  = caja.caja_chica_usd if caja else 0.0
            saldo_chica_bs   = caja.caja_chica_bs  if caja else 0.0

            # Verificar si este usuario ya tiene un turno activo
            # (caso: el sistema se cerró inesperadamente y se vuelve a abrir)
            self.turno_existente = sesion.query(Turno).filter(
                Turno.usuario_id == usuario["id"],
                Turno.activo == True,
            ).order_by(Turno.hora_inicio.desc()).first()

            if self.turno_existente:
                # Usar la tasa con la que se abrió el turno original
                self.tasa_actual = self.turno_existente.tasa_inicial
        finally:
            sesion.close()

        # Campos del formulario (solo se usan si no hay turno activo)
        self.campo_usd = ft.TextField(
            label="Efectivo USD en Caja",
            value=f"{saldo_chica_usd:.2f}",
            prefix_text="$ ", expand=True,
        )
        self.campo_bs = ft.TextField(
            label="Efectivo Bs en Caja",
            value=f"{saldo_chica_bs:.2f}",
            prefix_text="Bs ", expand=True,
        )
        self.campo_tasa = ft.TextField(
            label="Tasa de Cambio de Hoy",
            value=f"{self.tasa_actual:.2f}",
            expand=True,
        )

    def confirmar_apertura(self, evento):
        """
        Crea el turno en la BD, actualiza la tasa global y sincroniza la caja.
        Llama al callback al_completar con la tasa ingresada.
        """
        sesion = SesionLocal()
        try:
            usd_fisico   = float(self.campo_usd.value)
            bs_fisico    = float(self.campo_bs.value)
            tasa_ingresada = float(self.campo_tasa.value)

            # 1. Crear el registro del turno
            nuevo_turno = Turno(
                usuario_id   = self.usuario['id'],
                hora_inicio  = datetime.now(),
                inicial_usd  = usd_fisico,
                inicial_bs   = bs_fisico,
                tasa_inicial = tasa_ingresada,
                activo       = True,
            )
            sesion.add(nuevo_turno)

            # 2. Actualizar la tasa en la tabla de configuración global
            config_tasa = sesion.query(Configuracion).filter(
                Configuracion.clave == "exchange_rate"
            ).first()
            if config_tasa:
                config_tasa.valor = str(tasa_ingresada)

            # 3. Sincronizar los saldos físicos de la caja chica
            caja_bd = sesion.query(Caja).first()
            if caja_bd:
                caja_bd.caja_chica_usd       = usd_fisico
                caja_bd.caja_chica_bs        = bs_fisico
                caja_bd.ultima_actualizacion = datetime.now()

            sesion.commit()

            # Guardar el ID del turno en la sesión de la página para el cierre posterior
            self.pagina.session.set("id_turno_actual", nuevo_turno.id)

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
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error al abrir turno: {error}"),
                bgcolor=ft.Colors.RED_700,
            ))
        finally:
            sesion.close()

    def mostrar(self):
        """
        Si el usuario ya tiene un turno activo (el sistema se reinició),
        omite el diálogo y entra directo al dashboard reutilizando ese turno.
        """
        if self.turno_existente:
            # Registrar el ID del turno en la sesión de página para el cierre
            self.pagina.session.set("id_turno_actual", self.turno_existente.id)
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