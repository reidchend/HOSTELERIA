# modules/rooms/reservaciones.py
"""
Módulo de gestión de reservaciones.
Permite ver, crear, confirmar, cancelar, asignar habitación y convertir en check-in.
"""
import flet as ft
from datetime import datetime, date, timedelta
from utils.decimal_utils import Decimal
from utils.db import sesion
from database.connection import SesionLocal
from database.models import (
    Reservacion, EstadoReservacion, TipoHabitacion, Configuracion,
    Habitacion, EstadoHabitacion, Huesped, Estadia, TipoEstadia,
    FolioLinea, TipoLinea, LedgerMovimiento, TipoMovimiento,
)
from sqlalchemy.orm import selectinload
from modules.finance.bitacora import registrar as _bita
from database.models import TipoEvento
from modules.finance.engine import folio as folio_engine
from utils.calculos_financieros import leer_config_financiera


_COLOR_ESTADO = {
    EstadoReservacion.PENDIENTE:  (ft.Colors.AMBER_700,   "#FFF8E1",   "PENDIENTE"),
    EstadoReservacion.CONFIRMADA: (ft.Colors.BLUE_700,    "#E3F2FD",   "CONFIRMADA"),
    EstadoReservacion.CONVERTIDA: (ft.Colors.GREEN_700,   "#E8F5E9",   "CHECK-IN"),
    EstadoReservacion.CANCELADA:  (ft.Colors.GREY_500,    "#F5F5F5",   "CANCELADA"),
}


class PantallaReservaciones(ft.Container):

    def __init__(self, pagina: ft.Page, estado_app: dict, al_actualizar=None):
        super().__init__()
        self.pagina = pagina
        self.estado_app = estado_app
        self.al_actualizar = al_actualizar
        self.expand = True
        self.padding = ft.padding.symmetric(horizontal=28, vertical=20)
        self._filtro = "activas"
        self._construir()

    def _cargar(self) -> list:
        sesion = SesionLocal()
        try:
            q = sesion.query(Reservacion).options(selectinload(Reservacion.habitacion)).order_by(Reservacion.creado_en.desc())
            if self._filtro == "activas":
                q = q.filter(Reservacion.estado.in_([EstadoReservacion.PENDIENTE, EstadoReservacion.CONFIRMADA]))
            return q.all()
        finally:
            sesion.close()

    def _cargar_tipos(self) -> list:
        sesion = SesionLocal()
        try:
            return sesion.query(TipoHabitacion).order_by(TipoHabitacion.nombre).all()
        finally:
            sesion.close()

    def _refrescar(self):
        self.content = self._crear_contenido()
        self.update()

    def _construir(self):
        self.content = self._crear_contenido()

    def _crear_contenido(self):
        reservas = self._cargar()
        tipos = self._cargar_tipos()
        total_pend = sum(1 for r in reservas if r.estado == EstadoReservacion.PENDIENTE)
        total_conf = sum(1 for r in reservas if r.estado == EstadoReservacion.CONFIRMADA)

        def chip(valor, label, color):
            return ft.Container(
                content=ft.Row([ft.Text(str(valor), size=16, weight="bold", color=color), ft.Text(label, size=11, color=ft.Colors.GREY_500)], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.WHITE, border=ft.border.all(1, ft.Colors.with_opacity(0.25, color)),
                border_radius=8, padding=ft.padding.symmetric(horizontal=14, vertical=8),
            )

        sheet_ok = self._sheet_id_guardado()

        toolbar = ft.Row([
            ft.Icon(ft.Icons.EVENT_AVAILABLE, color=ft.Colors.BLUE_700, size=18),
            ft.Text("Reservaciones", size=20, weight="bold", color=ft.Colors.BLUE_GREY_900),
            chip(total_pend, "pendientes", ft.Colors.AMBER_700),
            chip(total_conf, "confirmadas", ft.Colors.BLUE_700),
            chip(len(reservas), "total", ft.Colors.GREY_500),
            ft.Container(expand=True),
            ft.TextButton("Ver todas" if self._filtro == "activas" else "Solo activas", icon=ft.Icons.FILTER_LIST, style=ft.ButtonStyle(color=ft.Colors.GREY_600), on_click=lambda _: self._toggle_filtro()),
            ft.ElevatedButton(
                "Importar web" if sheet_ok else "Configurar Sheet",
                icon=ft.Icons.CLOUD_DOWNLOAD if sheet_ok else ft.Icons.SETTINGS,
                style=ft.ButtonStyle(bgcolor=ft.Colors.PURPLE_50, color=ft.Colors.PURPLE_800, shape=ft.RoundedRectangleBorder(radius=8), side=ft.BorderSide(1, ft.Colors.PURPLE_200)),
                on_click=lambda _: (self._importar_directo() if sheet_ok else self._dlg_importar()),
            ),
            ft.IconButton(icon=ft.Icons.TUNE, icon_color=ft.Colors.PURPLE_300, icon_size=16, tooltip="Configurar Sheet", on_click=lambda _: self._dlg_importar(), visible=sheet_ok),
            ft.ElevatedButton("Nueva", icon=ft.Icons.ADD, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, on_click=lambda _: self._dlg_nueva(tipos)),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        if not reservas:
            lista = ft.Column([ft.Container(height=40), ft.Row([ft.Icon(ft.Icons.EVENT_BUSY, size=36, color=ft.Colors.GREY_300), ft.Text("No hay reservaciones" + (" activas" if self._filtro == "activas" else ""), size=14, color=ft.Colors.GREY_400, italic=True)], alignment=ft.MainAxisAlignment.CENTER, spacing=10)])
        else:
            lista = ft.Column(controls=[self._tarjeta(r, tipos) for r in reservas], spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

        return ft.Column([toolbar, ft.Divider(height=1, color=ft.Colors.GREY_200), lista], spacing=10, expand=True)

    def _tarjeta(self, r: Reservacion, tipos: list) -> ft.Container:
        color, bg, etiq = _COLOR_ESTADO.get(r.estado, (ft.Colors.GREY_500, ft.Colors.GREY_100, "—"))
        noches = (r.fecha_salida - r.fecha_entrada).days
        precio = 0.0
        for t in tipos:
            if t.nombre == r.tipo_habitacion:
                precio = float(t.precio_actual_usd) * noches
                break
        hab_info = f"Hab. {r.habitacion.numero}" if r.habitacion else ""

        acciones = []
        if r.estado in [EstadoReservacion.PENDIENTE, EstadoReservacion.CONFIRMADA]:
            acciones.append(ft.TextButton("Detalles", icon=ft.Icons.VISIBILITY_OUTLINED, style=ft.ButtonStyle(color=ft.Colors.BLUE_700), on_click=lambda _, res=r: self._ver_detalles(res, tipos)))
            if r.estado == EstadoReservacion.PENDIENTE:
                acciones.append(ft.TextButton("Confirmar", icon=ft.Icons.CHECK_CIRCLE_OUTLINE, style=ft.ButtonStyle(color=ft.Colors.BLUE_700), on_click=lambda _, rid=r.id: self._confirmar(rid)))
            if not r.habitacion_id:
                acciones.append(ft.TextButton("Asignar Hab.", icon=ft.Icons.MEETING_ROOM_OUTLINED, style=ft.ButtonStyle(color=ft.Colors.GREEN_700), on_click=lambda _, res=r: self._asignar_habitacion(res)))
            acciones.append(ft.TextButton("Cancelar", icon=ft.Icons.CANCEL_OUTLINED, style=ft.ButtonStyle(color=ft.Colors.RED_400), on_click=lambda _, rid=r.id: self._cancelar(rid)))
        elif r.estado == EstadoReservacion.CONVERTIDA:
            acciones.append(ft.TextButton("Ver Estadía", icon=ft.Icons.VISIBILITY_OUTLINED, style=ft.ButtonStyle(color=ft.Colors.GREEN_700), on_click=lambda _, rid=r.id: self._ver_estadia_convertida(rid)))

        return ft.Container(
            content=ft.Row([
                ft.Container(width=4, bgcolor=color, border_radius=4),
                ft.Column([
                    ft.Row([
                        ft.Text(f"{r.nombre} {r.apellido}", size=13, weight="bold", color=ft.Colors.BLUE_GREY_900, expand=True),
                        ft.Container(content=ft.Text("🌐 Web" if r.origen == "web" else "Sistema", size=9, color=ft.Colors.WHITE), bgcolor=ft.Colors.PURPLE_600 if r.origen == "web" else ft.Colors.BLUE_GREY_500, padding=ft.padding.symmetric(horizontal=6, vertical=2), border_radius=4),
                        ft.Container(content=ft.Text(etiq, size=9, weight="bold", color=ft.Colors.WHITE), bgcolor=color, padding=ft.padding.symmetric(horizontal=8, vertical=3), border_radius=6),
                    ], spacing=6),
                    ft.Row([
                        ft.Container(content=ft.Text(r.tipo_habitacion, size=11, weight="bold", color=color), bgcolor=bg, padding=ft.padding.symmetric(horizontal=7, vertical=3), border_radius=5, border=ft.border.all(1, ft.Colors.with_opacity(0.25, color))),
                        ft.Text("│", color=ft.Colors.GREY_300),
                        ft.Icon(ft.Icons.CALENDAR_TODAY, size=11, color=ft.Colors.GREY_400),
                        ft.Text(f"{r.fecha_entrada.strftime('%d/%m/%y')} → {r.fecha_salida.strftime('%d/%m/%y')} · {noches}n", size=11, color=ft.Colors.GREY_600),
                        ft.Text("│", color=ft.Colors.GREY_300),
                        ft.Icon(ft.Icons.PEOPLE_OUTLINE, size=11, color=ft.Colors.GREY_400),
                        ft.Text(str(r.num_huespedes), size=11, color=ft.Colors.GREY_600),
                        ft.Container(expand=True),
                        ft.Text(f"~${precio:,.0f}" if precio else "", size=12, weight="bold", color=ft.Colors.GREEN_700),
                    ], spacing=5),
                    ft.Row([
                        ft.Icon(ft.Icons.PHONE, size=11, color=ft.Colors.GREY_400),
                        ft.Text(r.telefono or "—", size=11, color=ft.Colors.GREY_500),
                        ft.Text("·", color=ft.Colors.GREY_300, size=11),
                        ft.Text(r.documento or "Sin doc.", size=11, color=ft.Colors.GREY_500),
                        ft.Text("·", color=ft.Colors.GREY_300, size=11),
                        ft.Text(r.creado_en.strftime("%d/%m %H:%M"), size=10, color=ft.Colors.GREY_400),
                        ft.Container(expand=True),
                        *acciones,
                    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Text(f"🏠 {hab_info}", size=10, color=ft.Colors.GREEN_700, weight="bold") if hab_info else ft.Container(height=0),
                    ft.Text(f"📝 {r.notas}", size=10, color=ft.Colors.GREY_500, italic=True) if r.notas else ft.Container(height=0),
                ], spacing=5, expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=ft.Colors.WHITE, border=ft.border.all(1, ft.Colors.GREY_200), border_radius=10,
            padding=ft.padding.symmetric(horizontal=10, vertical=10),
        )

    def _dlg_nueva(self, tipos: list):
        hoy = date.today()
        manana = hoy + timedelta(days=1)
        tf_nombre = ft.TextField(label="Nombres *", expand=True)
        tf_apellido = ft.TextField(label="Apellidos *", expand=True)
        tf_doc = ft.TextField(label="Documento", width=160)
        tf_tel = ft.TextField(label="Teléfono", expand=True)
        tf_email = ft.TextField(label="Correo electrónico", expand=True)
        tf_nac = ft.TextField(label="Nacionalidad", value="Venezolano/a", expand=True)
        tf_entrada = ft.TextField(label="Fecha entrada *", value=hoy.strftime("%Y-%m-%d"), hint_text="YYYY-MM-DD", width=150)
        tf_salida = ft.TextField(label="Fecha salida *", value=manana.strftime("%Y-%m-%d"), hint_text="YYYY-MM-DD", width=150)
        tf_huespedes = ft.TextField(label="N° huéspedes", value="1", width=100, keyboard_type=ft.KeyboardType.NUMBER)
        tf_notas = ft.TextField(label="Observaciones", multiline=True, min_lines=2, expand=True)
        dd_tipo = ft.Dropdown(label="Tipo de habitación *", options=[ft.dropdown.Option(t.nombre) for t in tipos], value=tipos[0].nombre if tipos else None, expand=True)
        dd_habitacion = ft.Dropdown(label="Habitación (opcional)", options=[], value=None, expand=True)
        txt_error = ft.Text("", color=ft.Colors.RED_700, size=11)

        def _cargar_habs(tipo_nombre):
            s = SesionLocal()
            try:
                habs = s.query(Habitacion).filter(Habitacion.tipo == tipo_nombre, Habitacion.estado == EstadoHabitacion.FREE).all()
                dd_habitacion.options = [ft.dropdown.Option(str(h.id), f"Hab. {h.numero} (Piso {h.piso})") for h in habs]
                dd_habitacion.value = None
            finally:
                s.close()

        def _on_tipo_change(e):
            if dd_tipo.value:
                _cargar_habs(dd_tipo.value)
                try:
                    dd_habitacion.update()
                except Exception:
                    pass

        dd_tipo.on_change = _on_tipo_change
        if tipos:
            _cargar_habs(tipos[0].nombre)

        def guardar(_):
            if not tf_nombre.value or not tf_apellido.value:
                txt_error.value = "Nombre y apellido son obligatorios."; txt_error.update(); return
            if not dd_tipo.value:
                txt_error.value = "Selecciona el tipo de habitación."; txt_error.update(); return
            try:
                entrada = datetime.strptime(tf_entrada.value, "%Y-%m-%d").date()
                salida = datetime.strptime(tf_salida.value, "%Y-%m-%d").date()
                if salida <= entrada:
                    txt_error.value = "La fecha de salida debe ser posterior a la entrada."; txt_error.update(); return
            except ValueError:
                txt_error.value = "Fechas inválidas. Usa formato YYYY-MM-DD."; txt_error.update(); return

            sesion = SesionLocal()
            try:
                nueva = Reservacion(
                    nombre=tf_nombre.value.strip(), apellido=tf_apellido.value.strip(),
                    documento=tf_doc.value.strip() or None, telefono=tf_tel.value.strip() or None,
                    email=tf_email.value.strip() or None, nacionalidad=tf_nac.value.strip() or None,
                    tipo_habitacion=dd_tipo.value, fecha_entrada=entrada, fecha_salida=salida,
                    num_huespedes=int(tf_huespedes.value or 1), notas=tf_notas.value.strip() or None,
                    estado=EstadoReservacion.PENDIENTE, origen="sistema",
                )
                hab_id = dd_habitacion.value
                if hab_id:
                    hab_id = int(hab_id)
                    hab = sesion.get(Habitacion, hab_id)
                    if hab:
                        nueva.habitacion_id = hab_id
                        hab.estado = EstadoHabitacion.RESERVED
                sesion.add(nueva)
                sesion.flush()
                _bita(sesion=sesion, pagina=self.pagina, tipo=TipoEvento.RESERVACION,
                      concepto=f"Reservación — {nueva.nombre} {nueva.apellido} · {nueva.tipo_habitacion}",
                      notificar_telegram=False)
                sesion.commit()
                nueva_id = nueva.id
                self.pagina.close(dlg)

                async def _mostrar_pregunta():
                    import asyncio
                    await asyncio.sleep(0.3)
                    self._preguntar_pago_reservacion(nueva_id)
                    await asyncio.sleep(0.5)
                    self._refrescar()
                self.pagina.run_task(_mostrar_pregunta)
            except Exception as e:
                sesion.rollback()
                txt_error.value = str(e); txt_error.update()
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.EVENT_AVAILABLE, color=ft.Colors.BLUE_700), ft.Text("Nueva Reservación", size=16, weight="bold")], spacing=8),
            content=ft.Container(width=520, content=ft.Column([
                ft.Text("Datos del titular", size=11, weight="bold", color=ft.Colors.GREY_600),
                ft.Row([tf_nombre, tf_apellido], spacing=10),
                ft.Row([tf_doc, tf_tel], spacing=10),
                ft.Row([tf_email, tf_nac], spacing=10),
                ft.Divider(height=8),
                ft.Text("Reservación", size=11, weight="bold", color=ft.Colors.GREY_600),
                dd_tipo, dd_habitacion,
                ft.Row([tf_entrada, tf_salida, tf_huespedes], spacing=10),
                tf_notas, txt_error,
            ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO), height=480),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton("Guardar reservación", icon=ft.Icons.SAVE, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, on_click=guardar),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _preguntar_pago_reservacion(self, reserva_id):
        sesion = SesionLocal()
        try:
            reserva = sesion.query(Reservacion).options(selectinload(Reservacion.habitacion)).filter(Reservacion.id == reserva_id).first()
            if not reserva:
                return
            noches = (reserva.fecha_salida - reserva.fecha_entrada).days
            s2 = SesionLocal()
            precio = 0.0
            try:
                tipo = s2.query(TipoHabitacion).filter(TipoHabitacion.nombre == reserva.tipo_habitacion).first()
                if tipo:
                    precio = float(tipo.precio_actual_usd) * noches
            finally:
                s2.close()

            def _ir_a_pagar(_):
                self.pagina.close(dlg_preguntar)
                self._abrir_pago_reservacion(reserva_id)

            def _omitir_pago(_):
                self.pagina.close(dlg_preguntar)
                # No enviar mensaje - la reservación queda pendiente sin notificación

            dlg_preguntar = ft.AlertDialog(
                modal=True, title=ft.Text("Reservación Creada"),
                content=ft.Text(
                    f"Reservación de {reserva.nombre} {reserva.apellido}\n"
                    f"Habitación: {reserva.tipo_habitacion}"
                    + (f" - Hab. {reserva.habitacion.numero}" if reserva.habitacion else " (sin asignar)")
                    + f"\nNoches: {noches}\nTotal: ${precio:.2f}\n\n¿Desea proceder al pago ahora?"
                ),
                actions=[
                    ft.TextButton("Omitir", on_click=_omitir_pago),
                    ft.ElevatedButton("Sí, proceder al pago", on_click=_ir_a_pagar),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.pagina.open(dlg_preguntar)
        finally:
            sesion.close()

    def _abrir_pago_reservacion(self, reserva_id):
        sesion = SesionLocal()
        try:
            reserva = sesion.query(Reservacion).options(selectinload(Reservacion.habitacion)).filter(Reservacion.id == reserva_id).first()
            if not reserva:
                return
            noches = (reserva.fecha_salida - reserva.fecha_entrada).days
            s2 = SesionLocal()
            precio = 0.0
            tipo_obj = None
            try:
                tipo_obj = s2.query(TipoHabitacion).filter(TipoHabitacion.nombre == reserva.tipo_habitacion).first()
                if tipo_obj:
                    precio = float(tipo_obj.precio_actual_usd) * noches
            finally:
                s2.close()

            estadia_temp = Estadia(
                habitacion_id=reserva.habitacion_id if reserva.habitacion_id else 0,
                entrada=datetime.combine(reserva.fecha_entrada, datetime.min.time()),
                salida=datetime.combine(reserva.fecha_salida, datetime.min.time()),
                activa=False, tipo=TipoEstadia.NOCHE,
                notas=f"Reservación #{reserva_id} - {reserva.nombre} {reserva.apellido}",
            )
            sesion.add(estadia_temp)
            sesion.flush()
            config = leer_config_financiera(sesion)
            precio_dec = tipo_obj.precio_actual_usd if tipo_obj else 0
            linea = folio_engine.crear_linea_hospedaje(
                sesion=sesion, estadia_id=estadia_temp.id,
                habitacion_numero=reserva.habitacion.numero if reserva.habitacion else "N/A",
                noches=noches, precio_noche_usd=precio_dec, config=config,
                concepto_extra=f"Reservación {reserva.nombre} {reserva.apellido}", aplica_iva=True,
            )
            sesion.commit()

            from modules.finance.payment_dialog import DialogoPago

            def al_completar_pago(pagos_sesion=None):
                print(f"[DEBUG Reservas] al_completar_pago called, pagos_sesion={pagos_sesion}")
                self._enviar_mensaje_reservacion_pagada(reserva_id, pagos_sesion)
                self._refrescar()

            dlg_pago = DialogoPago(
                self.pagina, estadia_temp, precio,
                al_completar=al_completar_pago, lineas_ids=[linea.id],
                checkin_info={
                    "habitacion": f"Reserva {reserva.nombre}", "monto": precio,
                    "nombre": f"{reserva.nombre} {reserva.apellido}",
                    "noches": noches, "fecha_salida": reserva.fecha_salida.strftime("%d/%m/%Y"),
                    "es_grupo": False,
                    "es_pago_reservacion": True,
                },
            )
            dlg_pago.mostrar()
        except Exception as e:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(ft.Text(f"Error al abrir pago: {e}"), bgcolor=ft.Colors.RED_700))
        finally:
            sesion.close()

    def _enviar_mensaje_reservacion_pendiente(self, reserva_id):
        try:
            from modules.notifications import telegram as tg
            from modules.notifications.formatter import reservacion_pendiente_mensaje
            sesion = SesionLocal()
            try:
                reserva = sesion.query(Reservacion).options(selectinload(Reservacion.habitacion)).filter(Reservacion.id == reserva_id).first()
                if not reserva:
                    return
                noches = (reserva.fecha_salida - reserva.fecha_entrada).days
                s2 = SesionLocal()
                precio = 0.0
                try:
                    tipo = s2.query(TipoHabitacion).filter(TipoHabitacion.nombre == reserva.tipo_habitacion).first()
                    if tipo:
                        precio = float(tipo.precio_actual_usd) * noches
                finally:
                    s2.close()
                msg = reservacion_pendiente_mensaje(
                    nombre=f"{reserva.nombre} {reserva.apellido}",
                    tipo_habitacion=reserva.tipo_habitacion,
                    fecha_entrada=reserva.fecha_entrada.strftime("%d/%m/%Y"),
                    fecha_salida=reserva.fecha_salida.strftime("%d/%m/%Y"),
                    noches=noches, total=precio,
                )
                tg.enviar_mensaje(msg)
            finally:
                sesion.close()
        except Exception as e:
            print(f"[Reservaciones] Error enviando mensaje pendiente: {e}")

    def _enviar_mensaje_reservacion_pagada(self, reserva_id, pagos_sesion=None):
        try:
            from modules.notifications import telegram as tg
            from modules.notifications.formatter import reservacion_pagada_mensaje
            sesion = SesionLocal()
            try:
                reserva = sesion.query(Reservacion).options(selectinload(Reservacion.habitacion)).filter(Reservacion.id == reserva_id).first()
                if not reserva:
                    return
                noches = (reserva.fecha_salida - reserva.fecha_entrada).days
                pagos = []
                if pagos_sesion:
                    for p in pagos_sesion:
                        pagos.append({
                            "metodo": p.get("metodo", "Efectivo $"),
                            "monto_usd": float(p.get("monto_usd", 0)),
                            "monto_bs": float(p.get("monto_bs", 0)),
                            "referencia": p.get("referencia", ""),
                            "telefono_pm": p.get("telefono_pm", ""),
                        })
                s2 = SesionLocal()
                precio = 0.0
                try:
                    tipo = s2.query(TipoHabitacion).filter(TipoHabitacion.nombre == reserva.tipo_habitacion).first()
                    if tipo:
                        precio = float(tipo.precio_actual_usd) * noches
                finally:
                    s2.close()
                msg = reservacion_pagada_mensaje(
                    nombre=f"{reserva.nombre} {reserva.apellido}",
                    tipo_habitacion=reserva.tipo_habitacion,
                    fecha_entrada=reserva.fecha_entrada.strftime("%d/%m/%Y"),
                    fecha_salida=reserva.fecha_salida.strftime("%d/%m/%Y"),
                    noches=noches, total=precio, pagos=pagos,
                )
                tg.enviar_mensaje(msg)
            finally:
                sesion.close()
        except Exception as e:
            print(f"[Reservaciones] Error enviando mensaje pagada: {e}")

    def _confirmar(self, reserva_id: int):
        sesion = SesionLocal()
        try:
            r = sesion.get(Reservacion, reserva_id)
            r.estado = EstadoReservacion.CONFIRMADA
            r.confirmado_en = datetime.now()
            _bita(sesion=sesion, pagina=self.pagina, tipo=TipoEvento.RESERVACION, concepto=f"Reservación CONFIRMADA — {r.nombre} {r.apellido}", notificar_telegram=False)
            sesion.commit()
            self._refrescar()
            self.pagina.open(ft.SnackBar(ft.Text("Reservación confirmada"), bgcolor=ft.Colors.BLUE_700))
        except Exception as e:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(ft.Text(str(e)), bgcolor=ft.Colors.RED_700))
        finally:
            sesion.close()

    def _cancelar(self, reserva_id: int):
        def ejecutar(_):
            self.pagina.close(dlg)
            sesion = SesionLocal()
            try:
                r = sesion.get(Reservacion, reserva_id)
                r.estado = EstadoReservacion.CANCELADA
                _bita(sesion=sesion, pagina=self.pagina, tipo=TipoEvento.RESERVACION, concepto=f"Reservación CANCELADA — {r.nombre} {r.apellido}")
                sesion.commit()
                self._refrescar()
            except Exception as e:
                sesion.rollback()
                self.pagina.open(ft.SnackBar(ft.Text(str(e)), bgcolor=ft.Colors.RED_700))
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("¿Cancelar reservación?"),
            content=ft.Text("Esta acción no se puede deshacer.", color=ft.Colors.GREY_600),
            actions=[
                ft.TextButton("Volver", on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton("Sí, cancelar", bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE, on_click=ejecutar),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _asignar_habitacion(self, reserva: Reservacion):
        sesion = SesionLocal()
        try:
            habs_libres = sesion.query(Habitacion).filter(Habitacion.tipo == reserva.tipo_habitacion, Habitacion.estado == EstadoHabitacion.FREE).all()
            if not habs_libres:
                self.pagina.open(ft.SnackBar(ft.Text(f"No hay habitaciones {reserva.tipo_habitacion} disponibles"), bgcolor=ft.Colors.RED_700))
                return
            opciones = [ft.dropdown.Option(str(h.id), f"Hab. {h.numero} (Piso {h.piso})") for h in habs_libres]
            dd_hab = ft.Dropdown(label="Seleccionar Habitación", options=opciones, value=str(habs_libres[0].id), expand=True)

            def confirmar(_):
                hab_id = int(dd_hab.value)
                hab = sesion.get(Habitacion, hab_id)
                if hab:
                    reserva.habitacion_id = hab.id
                    hab.estado = EstadoHabitacion.RESERVED
                    _bita(sesion=sesion, pagina=self.pagina, tipo=TipoEvento.RESERVACION, concepto=f"Hab. {hab.numero} asignada a {reserva.nombre} {reserva.apellido}")
                    sesion.commit()
                    self.pagina.close(dlg_asignar)
                    self._refrescar()
                    self.pagina.open(ft.SnackBar(ft.Text(f"Hab. {hab.numero} asignada a {reserva.nombre} {reserva.apellido}"), bgcolor=ft.Colors.GREEN_700))
                sesion.close()

            dlg_asignar = ft.AlertDialog(
                modal=True, title=ft.Text(f"Asignar Habitación - {reserva.nombre} {reserva.apellido}"),
                content=ft.Container(content=ft.Column([
                    ft.Text(f"Tipo: {reserva.tipo_habitacion}", size=12, color=ft.Colors.GREY_600),
                    ft.Text(f"Entrada: {reserva.fecha_entrada.strftime('%d/%m/%Y')}", size=12),
                    ft.Text(f"Salida: {reserva.fecha_salida.strftime('%d/%m/%Y')}", size=12),
                    ft.Divider(), dd_hab,
                ], spacing=8), width=400),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg_asignar)),
                    ft.ElevatedButton("Asignar", icon=ft.Icons.CHECK, on_click=confirmar),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            self.pagina.open(dlg_asignar)
        finally:
            sesion.close()

    def _ver_detalles(self, reserva: Reservacion, tipos: list):
        color, bg, etiq = _COLOR_ESTADO.get(reserva.estado, (ft.Colors.GREY_500, ft.Colors.GREY_100, "—"))
        noches = (reserva.fecha_salida - reserva.fecha_entrada).days
        precio = 0.0
        for t in tipos:
            if t.nombre == reserva.tipo_habitacion:
                precio = float(t.precio_actual_usd) * noches
                break
        hab_info = f"Hab. {reserva.habitacion.numero}" if reserva.habitacion else "Sin asignar"

        contenido = ft.Column([
            ft.Container(content=ft.Column([
                ft.Row([ft.Text(f"{reserva.nombre} {reserva.apellido}", size=18, weight="bold"),
                        ft.Container(content=ft.Text(etiq, size=10, weight="bold", color=ft.Colors.WHITE), bgcolor=color, padding=ft.padding.symmetric(horizontal=10, vertical=4), border_radius=6)]),
                ft.Text(f"Documento: {reserva.documento or 'No registrado'}", size=12),
                ft.Text(f"Teléfono: {reserva.telefono or 'No registrado'}", size=12),
                ft.Text(f"Email: {reserva.email or 'No registrado'}", size=12),
            ], spacing=5), padding=15, bgcolor=bg, border_radius=8),
            ft.Container(content=ft.Column([
                ft.Text("Detalles de la Reservación", size=14, weight="bold"),
                ft.Text(f"Tipo: {reserva.tipo_habitacion}", size=12),
                ft.Text(f"Habitación: {hab_info}", size=12),
                ft.Text(f"Entrada: {reserva.fecha_entrada.strftime('%d/%m/%Y')}", size=12),
                ft.Text(f"Salida: {reserva.fecha_salida.strftime('%d/%m/%Y')}", size=12),
                ft.Text(f"Noches: {noches}", size=12),
                ft.Text(f"Huéspedes: {reserva.num_huespedes}", size=12),
                ft.Text(f"Precio estimado: ${precio:,.2f}", size=14, weight="bold", color=ft.Colors.GREEN_700),
            ] + ([ft.Text(f"Notas: {reserva.notas}", size=12, italic=True)] if reserva.notas else []),
            spacing=5), padding=15, border=ft.border.all(1, ft.Colors.OUTLINE), border_radius=8),
        ], spacing=10, scroll=ft.ScrollMode.AUTO)

        acciones = []
        if reserva.estado in [EstadoReservacion.PENDIENTE, EstadoReservacion.CONFIRMADA]:
            if not reserva.habitacion_id:
                acciones.append(ft.ElevatedButton("Asignar Habitación", icon=ft.Icons.MEETING_ROOM, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, on_click=lambda _: (self.pagina.close(dlg), self._asignar_habitacion(reserva))))
            if reserva.estado == EstadoReservacion.PENDIENTE:
                acciones.append(ft.ElevatedButton("Confirmar", icon=ft.Icons.CHECK_CIRCLE, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, on_click=lambda _: (self.pagina.close(dlg), self._confirmar(reserva.id))))
            if reserva.habitacion_id:
                acciones.append(ft.ElevatedButton("Dar Entrada (Check-In)", icon=ft.Icons.LOGIN, bgcolor=ft.Colors.AMBER_700, color=ft.Colors.WHITE, on_click=lambda _: (self.pagina.close(dlg), self._convertir_checkin(reserva))))
            acciones.append(ft.ElevatedButton("Cancelar", icon=ft.Icons.CANCEL, bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE, on_click=lambda _: (self.pagina.close(dlg), self._cancelar(reserva.id))))

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Detalles de Reservación"),
            content=ft.Container(content=contenido, width=450, height=400),
            actions=acciones + [ft.TextButton("Cerrar", on_click=lambda _: self.pagina.close(dlg))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _convertir_checkin(self, reserva: Reservacion):
        from modules.rooms.checkin_reservacion import DialogoCheckInReservacion
        DialogoCheckInReservacion(pagina=self.pagina, reserva=reserva, al_completar=self._refrescar).mostrar()

    def _ver_estadia_convertida(self, reserva_id: int):
        sesion = SesionLocal()
        try:
            r = sesion.get(Reservacion, reserva_id)
            if r and r.estadia_id:
                estadia = sesion.get(Estadia, r.estadia_id)
                if estadia and estadia.habitacion:
                    from modules.rooms.details import DialogoDetallesHabitacion
                    DialogoDetallesHabitacion(pagina=self.pagina, habitacion=estadia.habitacion, estadia=estadia).mostrar()
                else:
                    self.pagina.open(ft.SnackBar(ft.Text("Estadía no encontrada")))
            else:
                self.pagina.open(ft.SnackBar(ft.Text("Esta reservación no tiene estadía asociada")))
        finally:
            sesion.close()

    def _toggle_filtro(self):
        self._filtro = "todas" if self._filtro == "activas" else "activas"
        self._refrescar()

    def _sheet_id_guardado(self) -> bool:
        sesion = SesionLocal()
        try:
            cfg = sesion.query(Configuracion).filter(Configuracion.clave == "google_sheet_id").first()
            return cfg is not None and cfg.valor is not None and cfg.valor.strip() != ""
        finally:
            sesion.close()

    def _dlg_importar(self):
        tf_sheet = ft.TextField(label="Google Sheet ID", hint_text="1aBcDeFgHiJkLmNoPqRsTuVwXyZ...", expand=True)
        txt_error = ft.Text("", color=ft.Colors.RED_700, size=11)
        sesion = SesionLocal()
        try:
            cfg = sesion.query(Configuracion).filter(Configuracion.clave == "google_sheet_id").first()
            if cfg:
                tf_sheet.value = cfg.valor
        finally:
            sesion.close()

        def guardar(_):
            if not tf_sheet.value or not tf_sheet.value.strip():
                txt_error.value = "Ingresa un Sheet ID válido."; txt_error.update(); return
            sesion = SesionLocal()
            try:
                cfg = sesion.query(Configuracion).filter(Configuracion.clave == "google_sheet_id").first()
                if cfg:
                    cfg.valor = tf_sheet.value.strip()
                else:
                    sesion.add(Configuracion(clave="google_sheet_id", valor=tf_sheet.value.strip()))
                sesion.commit()
                self.pagina.close(dlg)
                self._refrescar()
            except Exception as e:
                sesion.rollback()
                txt_error.value = str(e); txt_error.update()
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Configurar Google Sheet"),
            content=ft.Container(content=ft.Column([ft.Text("Ingresa el ID de la hoja de cálculo de Google que contiene las reservaciones web.", size=12, color=ft.Colors.GREY_600), tf_sheet, txt_error], spacing=10), width=450),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg)), ft.ElevatedButton("Guardar", icon=ft.Icons.SAVE, on_click=guardar)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _importar_directo(self):
        try:
            from modules.integrations.google_sheets import importar_reservaciones_web
            nuevas = importar_reservaciones_web(self.pagina)
            if nuevas:
                self._refrescar()
                self.pagina.open(ft.SnackBar(ft.Text(f"Se importaron {nuevas} reservaciones"), bgcolor=ft.Colors.GREEN_700))
            else:
                self.pagina.open(ft.SnackBar(ft.Text("No se encontraron nuevas reservaciones"), bgcolor=ft.Colors.BLUE_700))
        except ModuleNotFoundError:
            self.pagina.open(ft.SnackBar(ft.Text("Módulo de Google Sheets no instalado. Ejecuta: pip install gspread google-auth"), bgcolor=ft.Colors.RED_700))
        except Exception as e:
            self.pagina.open(ft.SnackBar(ft.Text(f"Error al importar: {e}"), bgcolor=ft.Colors.RED_700))
