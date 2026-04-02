# modules/rooms/checkin_reservacion.py
"""
Check-in desde una reservación confirmada.
Pre-rellena los datos del huésped y permite elegir la habitación disponible
del tipo reservado.
"""
import flet as ft
from datetime import datetime
from utils.decimal_utils import Decimal
from utils.db import sesion
from database.models import (
    Reservacion, EstadoReservacion, Huesped, Habitacion,
    EstadoHabitacion, Estadia,
)
from modules.finance.engine import folio as folio_engine
from modules.finance.bitacora import registrar as _bita
from database.models import TipoEvento
from utils.calculos_financieros import leer_config_financiera


class DialogoCheckInReservacion:

    def __init__(self, pagina: ft.Page, reserva: Reservacion, al_completar):
        self.pagina       = pagina
        self.reserva      = reserva
        self.al_completar = al_completar
        self.dialogo      = None

    def mostrar(self):
        sesion = SesionLocal()
        try:
            # Habitaciones disponibles del tipo solicitado
            habs_disp = (
                sesion.query(Habitacion)
                .filter(
                    Habitacion.tipo   == self.reserva.tipo_habitacion,
                    Habitacion.estado == EstadoHabitacion.FREE,
                )
                .order_by(Habitacion.numero)
                .all()
            )
        finally:
            sesion.close()

        if not habs_disp:
            self.pagina.open(ft.SnackBar(
                ft.Text(
                    f"No hay habitaciones {self.reserva.tipo_habitacion} "
                    f"disponibles en este momento.",
                    color=ft.Colors.WHITE,
                ),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return

        r = self.reserva

        # Dropdown de habitaciones disponibles
        dd_hab = ft.Dropdown(
            label=f"Habitación {r.tipo_habitacion} disponible *",
            options=[
                ft.dropdown.Option(
                    str(h.id),
                    f"Hab. {h.numero} — Piso {h.piso} — "
                    f"${float(h.precio_actual_usd):.2f}/noche",
                )
                for h in habs_disp
            ],
            value=str(habs_disp[0].id),
            expand=True,
        )

        # Campos pre-rellenados
        tf_nombre  = ft.TextField(label="Nombres",   value=r.nombre,   expand=True)
        tf_apell   = ft.TextField(label="Apellidos", value=r.apellido, expand=True)
        tf_doc     = ft.TextField(label="Documento", value=r.documento or "", width=160)
        tf_tel     = ft.TextField(label="Teléfono",  value=r.telefono or "", expand=True)
        tf_nac     = ft.TextField(label="Nacionalidad",
                                  value=r.nacionalidad or "Venezolano/a", expand=True)
        tf_entrada = ft.TextField(
            label="Fecha entrada",
            value=r.fecha_entrada.strftime("%Y-%m-%d"), width=150,
        )
        tf_salida  = ft.TextField(
            label="Fecha salida",
            value=r.fecha_salida.strftime("%Y-%m-%d"), width=150,
        )
        txt_error  = ft.Text("", color=ft.Colors.RED_700, size=11)

        def confirmar(_):
            if not dd_hab.value:
                txt_error.value = "Selecciona una habitación."
                txt_error.update(); return
            try:
                entrada = datetime.strptime(tf_entrada.value, "%Y-%m-%d")
                salida  = datetime.strptime(tf_salida.value,  "%Y-%m-%d")
            except ValueError:
                txt_error.value = "Fechas inválidas."
                txt_error.update(); return

            sesion = SesionLocal()
            try:
                hab_bd = sesion.get(Habitacion, int(dd_hab.value))

                # Crear o actualizar huésped
                huesped = (
                    sesion.query(Huesped)
                    .filter(Huesped.documento == tf_doc.value.strip())
                    .first()
                ) if tf_doc.value.strip() else None

                if not huesped:
                    huesped = Huesped(
                        documento    = tf_doc.value.strip() or None,
                        nombre       = tf_nombre.value.strip(),
                        apellido     = tf_apell.value.strip(),
                        telefono     = tf_tel.value.strip() or None,
                        nacionalidad = tf_nac.value.strip() or None,
                    )
                    sesion.add(huesped)
                else:
                    huesped.nombre       = tf_nombre.value.strip()
                    huesped.apellido     = tf_apell.value.strip()
                    huesped.telefono     = tf_tel.value.strip() or None
                    huesped.nacionalidad = tf_nac.value.strip() or None

                # Cambiar estado habitación
                hab_bd.estado = EstadoHabitacion.OCCUPIED

                # Crear estadía
                noches = max(1, (salida.date() - entrada.date()).days)
                estadia = Estadia(
                    habitacion_id = hab_bd.id,
                    entrada       = entrada,
                    salida        = salida,
                    activa        = True,
                )
                estadia.huespedes = [huesped]
                sesion.add(estadia)
                sesion.flush()

                # Crear línea de hospedaje en folio
                config = leer_config_financiera(sesion)
                folio_engine.crear_linea_hospedaje(
                    sesion,
                    estadia_id        = estadia.id,
                    habitacion_numero = hab_bd.numero,
                    noches            = noches,
                    precio_noche_usd  = hab_bd.precio_actual_usd,
                    config            = config,
                    concepto_extra    = (
                        f"Hospedaje — Hab. {hab_bd.numero} "
                        f"({noches} noche{'s' if noches != 1 else ''}) "
                        f"{entrada.strftime('%d/%m/%Y')} → "
                        f"{salida.strftime('%d/%m/%Y')}"
                    ),
                )

                # Marcar reservación como convertida
                reserva_bd = sesion.get(Reservacion, self.reserva.id)
                reserva_bd.estado     = EstadoReservacion.CONVERTIDA
                reserva_bd.estadia_id = estadia.id

                # Bitácora
                _bita(
                    sesion     = sesion,
                    pagina     = self.pagina,
                    tipo       = TipoEvento.CHECKIN,
                    habitacion = hab_bd.numero,
                    concepto   = (
                        f"Check-In desde reservación — {huesped.nombre_completo} · "
                        f"{noches} noche{'s' if noches != 1 else ''} · "
                        f"Sal. {salida.strftime('%d/%m/%Y')}"
                    ),
                    monto_usd  = float(
                        folio_engine.total_pendiente(sesion, estadia.id)
                    ),
                )

                sesion.commit()
                self.pagina.close(self.dialogo)
                self.pagina.open(ft.SnackBar(
                    ft.Text(
                        f"Check-In realizado — Hab. {hab_bd.numero} · "
                        f"{huesped.nombre_completo}"
                    ),
                    bgcolor=ft.Colors.GREEN_700,
                ))
                if self.al_completar:
                    self.al_completar()

            except Exception as e:
                sesion.rollback()
                txt_error.value = str(e)
                txt_error.update()
            finally:
                sesion.close()

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.LOGIN, color=ft.Colors.GREEN_700),
                ft.Text("Check-In desde Reservación", size=15, weight="bold"),
            ], spacing=8),
            content=ft.Container(
                width=500,
                content=ft.Column([
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.INFO_OUTLINE,
                                    color=ft.Colors.BLUE_700, size=14),
                            ft.Text(
                                f"Reservación de {r.tipo_habitacion} · "
                                f"{r.fecha_entrada.strftime('%d/%m/%Y')} → "
                                f"{r.fecha_salida.strftime('%d/%m/%Y')}",
                                size=12, color=ft.Colors.BLUE_700,
                            ),
                        ], spacing=6),
                        bgcolor=ft.Colors.BLUE_50,
                        padding=ft.padding.symmetric(horizontal=12, vertical=8),
                        border_radius=8,
                        border=ft.border.all(1, ft.Colors.BLUE_200),
                    ),
                    dd_hab,
                    ft.Divider(height=6),
                    ft.Row([tf_nombre, tf_apell], spacing=10),
                    ft.Row([tf_doc, tf_tel], spacing=10),
                    ft.Row([tf_nac], spacing=10),
                    ft.Row([tf_entrada, tf_salida], spacing=10),
                    txt_error,
                ], spacing=10, tight=True),
                height=400,
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(self.dialogo)),
                ft.ElevatedButton(
                    "Confirmar Check-In",
                    icon=ft.Icons.LOGIN,
                    bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,
                    on_click=confirmar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(self.dialogo)