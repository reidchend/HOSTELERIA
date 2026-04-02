# modules/rooms/reservaciones.py
"""
Módulo de gestión de reservaciones.
Permite ver, crear, confirmar, cancelar y convertir en check-in.
"""
import flet as ft
from datetime import datetime, date, timedelta
from utils.decimal_utils import Decimal
from utils.db import sesion
from database.models import (
    Reservacion, EstadoReservacion, TipoHabitacion, Configuracion,
    Habitacion, EstadoHabitacion, Huesped, Estadia,
)
from modules.finance.bitacora import registrar as _bita
from database.models import TipoEvento


# ── Colores por estado ────────────────────────────────────────────────────────
_COLOR_ESTADO = {
    EstadoReservacion.PENDIENTE:  (ft.Colors.AMBER_700,   ft.Colors.AMBER_50,   "PENDIENTE"),
    EstadoReservacion.CONFIRMADA: (ft.Colors.BLUE_700,    ft.Colors.BLUE_50,    "CONFIRMADA"),
    EstadoReservacion.CONVERTIDA: (ft.Colors.GREEN_700,   ft.Colors.GREEN_50,   "CHECK-IN"),
    EstadoReservacion.CANCELADA:  (ft.Colors.GREY_500,    ft.Colors.GREY_100,   "CANCELADA"),
}


# ══════════════════════════════════════════════════════════════════════════════
# PANTALLA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class PantallaReservaciones(ft.Container):

    def __init__(self, pagina: ft.Page, estado_app: dict, al_actualizar=None):
        super().__init__()
        self.pagina       = pagina
        self.estado_app   = estado_app
        self.al_actualizar = al_actualizar
        self.expand       = True
        self.padding      = ft.padding.symmetric(horizontal=28, vertical=20)
        self._filtro      = "activas"   # "activas" | "todas"
        self._construir()

    # ─────────────────────────────────────────────────────────────────────────
    # DATOS
    # ─────────────────────────────────────────────────────────────────────────

    def _cargar(self) -> list:
        sesion = SesionLocal()
        try:
            q = sesion.query(Reservacion).order_by(Reservacion.creado_en.desc())
            if self._filtro == "activas":
                q = q.filter(Reservacion.estado.in_([
                    EstadoReservacion.PENDIENTE,
                    EstadoReservacion.CONFIRMADA,
                ]))
            return q.all()
        finally:
            sesion.close()

    def _cargar_tipos(self) -> list:
        sesion = SesionLocal()
        try:
            return sesion.query(TipoHabitacion).order_by(TipoHabitacion.nombre).all()
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN
    # ─────────────────────────────────────────────────────────────────────────

    def _construir(self):
        reservas = self._cargar()
        tipos    = self._cargar_tipos()

        total_pend = sum(1 for r in reservas if r.estado == EstadoReservacion.PENDIENTE)
        total_conf = sum(1 for r in reservas if r.estado == EstadoReservacion.CONFIRMADA)
        sheet_ok   = self._sheet_id_guardado()

        # ── Chips de resumen ──────────────────────────────────────────────────
        def chip(valor, label, color):
            return ft.Container(
                content=ft.Row([
                    ft.Text(str(valor), size=16, weight="bold", color=color),
                    ft.Text(label, size=11, color=ft.Colors.GREY_500),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1, ft.Colors.with_opacity(0.25, color)),
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=14, vertical=8),
            )

        # ── Barra de herramientas ─────────────────────────────────────────────
        toolbar = ft.Row([
            ft.Icon(ft.Icons.EVENT_AVAILABLE, color=ft.Colors.BLUE_700, size=18),
            ft.Text("Reservaciones", size=20, weight="bold",
                    color=ft.Colors.BLUE_GREY_900),
            chip(total_pend, "pendientes", ft.Colors.AMBER_700),
            chip(total_conf, "confirmadas", ft.Colors.BLUE_700),
            chip(len(reservas), "total", ft.Colors.GREY_500),
            ft.Container(expand=True),
            # Filtro
            ft.TextButton(
                "Ver todas" if self._filtro == "activas" else "Solo activas",
                icon=ft.Icons.FILTER_LIST,
                style=ft.ButtonStyle(color=ft.Colors.GREY_600),
                on_click=lambda _: self._toggle_filtro(),
            ),
            # Importar
            ft.ElevatedButton(
                "Importar web" if sheet_ok else "Configurar Sheet",
                icon=ft.Icons.CLOUD_DOWNLOAD if sheet_ok else ft.Icons.SETTINGS,
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.PURPLE_50,
                    color=ft.Colors.PURPLE_800,
                    shape=ft.RoundedRectangleBorder(radius=8),
                    side=ft.BorderSide(1, ft.Colors.PURPLE_200),
                ),
                on_click=lambda _: (
                    self._importar_directo() if sheet_ok else self._dlg_importar()
                ),
            ),
            ft.IconButton(
                icon=ft.Icons.TUNE,
                icon_color=ft.Colors.PURPLE_300,
                icon_size=16,
                tooltip="Configurar Sheet",
                on_click=lambda _: self._dlg_importar(),
                visible=sheet_ok,
            ),
            # Nueva
            ft.ElevatedButton(
                "Nueva",
                icon=ft.Icons.ADD,
                bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
                on_click=lambda _: self._dlg_nueva(tipos),
            ),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # ── Lista de reservaciones ────────────────────────────────────────────
        if not reservas:
            lista = ft.Column([
                ft.Container(height=40),
                ft.Row([
                    ft.Icon(ft.Icons.EVENT_BUSY, size=36, color=ft.Colors.GREY_300),
                    ft.Text("No hay reservaciones" +
                            (" activas" if self._filtro == "activas" else ""),
                            size=14, color=ft.Colors.GREY_400, italic=True),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            ])
        else:
            lista = ft.Column(
                controls=[self._tarjeta(r, tipos) for r in reservas],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )

        self.content = ft.Column([
            toolbar,
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            lista,
        ], spacing=10, expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TARJETA DE RESERVACIÓN
    # ─────────────────────────────────────────────────────────────────────────

    def _tarjeta(self, r: Reservacion, tipos: list) -> ft.Container:
        color, bg, etiq = _COLOR_ESTADO.get(
            r.estado, (ft.Colors.GREY_500, ft.Colors.GREY_100, "—")
        )
        noches = (r.fecha_salida - r.fecha_entrada).days
        precio = 0.0
        for t in tipos:
            if t.nombre == r.tipo_habitacion:
                precio = float(t.precio_actual_usd) * noches
                break

        # Acciones
        acciones = []
        if r.estado == EstadoReservacion.PENDIENTE:
            acciones = [
                ft.TextButton("Confirmar",
                    icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                    style=ft.ButtonStyle(color=ft.Colors.BLUE_700),
                    on_click=lambda _, rid=r.id: self._confirmar(rid)),
                ft.TextButton("Cancelar",
                    icon=ft.Icons.CANCEL_OUTLINED,
                    style=ft.ButtonStyle(color=ft.Colors.RED_400),
                    on_click=lambda _, rid=r.id: self._cancelar(rid)),
            ]
        elif r.estado == EstadoReservacion.CONFIRMADA:
            acciones = [
                ft.ElevatedButton("Check-In",
                    icon=ft.Icons.LOGIN,
                    bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,
                    on_click=lambda _, res=r: self._convertir_checkin(res)),
                ft.TextButton("Cancelar",
                    icon=ft.Icons.CANCEL_OUTLINED,
                    style=ft.ButtonStyle(color=ft.Colors.RED_400),
                    on_click=lambda _, rid=r.id: self._cancelar(rid)),
            ]

        # Franja lateral de color según estado
        return ft.Container(
            content=ft.Row([
                # Franja izquierda de color
                ft.Container(width=4, bgcolor=color, border_radius=4),
                # Contenido
                ft.Column([
                    # Línea 1: nombre + badges
                    ft.Row([
                        ft.Text(f"{r.nombre} {r.apellido}",
                                size=13, weight="bold",
                                color=ft.Colors.BLUE_GREY_900, expand=True),
                        ft.Container(
                            content=ft.Text(
                                "🌐 Web" if r.origen == "web" else "Sistema",
                                size=9, color=ft.Colors.WHITE,
                            ),
                            bgcolor=ft.Colors.PURPLE_600 if r.origen == "web"
                                    else ft.Colors.BLUE_GREY_500,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=4,
                        ),
                        ft.Container(
                            content=ft.Text(etiq, size=9, weight="bold",
                                            color=ft.Colors.WHITE),
                            bgcolor=color,
                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            border_radius=6,
                        ),
                    ], spacing=6),
                    # Línea 2: tipo + fechas + precio
                    ft.Row([
                        ft.Container(
                            content=ft.Text(r.tipo_habitacion, size=11,
                                            weight="bold", color=color),
                            bgcolor=bg,
                            padding=ft.padding.symmetric(horizontal=7, vertical=3),
                            border_radius=5,
                            border=ft.border.all(1, ft.Colors.with_opacity(0.25, color)),
                        ),
                        ft.Text("│", color=ft.Colors.GREY_300),
                        ft.Icon(ft.Icons.CALENDAR_TODAY, size=11,
                                color=ft.Colors.GREY_400),
                        ft.Text(
                            f"{r.fecha_entrada.strftime('%d/%m/%y')} → "
                            f"{r.fecha_salida.strftime('%d/%m/%y')} "
                            f"· {noches}n",
                            size=11, color=ft.Colors.GREY_600,
                        ),
                        ft.Text("│", color=ft.Colors.GREY_300),
                        ft.Icon(ft.Icons.PEOPLE_OUTLINE, size=11,
                                color=ft.Colors.GREY_400),
                        ft.Text(str(r.num_huespedes), size=11,
                                color=ft.Colors.GREY_600),
                        ft.Container(expand=True),
                        ft.Text(f"~${precio:,.0f}" if precio else "",
                                size=12, weight="bold",
                                color=ft.Colors.GREEN_700),
                    ], spacing=5),
                    # Línea 3: contacto + doc
                    ft.Row([
                        ft.Icon(ft.Icons.PHONE, size=11, color=ft.Colors.GREY_400),
                        ft.Text(r.telefono or "—", size=11,
                                color=ft.Colors.GREY_500),
                        ft.Text("·", color=ft.Colors.GREY_300, size=11),
                        ft.Text(r.documento or "Sin doc.", size=11,
                                color=ft.Colors.GREY_500),
                        ft.Text("·", color=ft.Colors.GREY_300, size=11),
                        ft.Text(r.creado_en.strftime("%d/%m %H:%M"),
                                size=10, color=ft.Colors.GREY_400),
                        ft.Container(expand=True),
                        *acciones,
                    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    # Notas (solo si tiene)
                    ft.Text(f"📝 {r.notas}", size=10, color=ft.Colors.GREY_500,
                            italic=True) if r.notas else ft.Container(height=0),
                ], spacing=5, expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=ft.Colors.WHITE,
            border=ft.border.all(1, ft.Colors.GREY_200),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=10, vertical=10),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # DIÁLOGO NUEVA RESERVACIÓN
    # ─────────────────────────────────────────────────────────────────────────

    def _dlg_nueva(self, tipos: list):
        hoy      = date.today()
        manana   = hoy + timedelta(days=1)

        tf_nombre    = ft.TextField(label="Nombres *", expand=True)
        tf_apellido  = ft.TextField(label="Apellidos *", expand=True)
        tf_doc       = ft.TextField(label="Documento", width=160)
        tf_tel       = ft.TextField(label="Teléfono", expand=True)
        tf_email     = ft.TextField(label="Correo electrónico", expand=True)
        tf_nac       = ft.TextField(label="Nacionalidad",
                                    value="Venezolano/a", expand=True)
        tf_entrada   = ft.TextField(
            label="Fecha entrada *", value=hoy.strftime("%Y-%m-%d"),
            hint_text="YYYY-MM-DD", width=150,
        )
        tf_salida    = ft.TextField(
            label="Fecha salida *", value=manana.strftime("%Y-%m-%d"),
            hint_text="YYYY-MM-DD", width=150,
        )
        tf_huespedes = ft.TextField(
            label="N° huéspedes", value="1", width=100,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        tf_notas     = ft.TextField(
            label="Observaciones", multiline=True, min_lines=2, expand=True,
        )
        dd_tipo      = ft.Dropdown(
            label="Tipo de habitación *",
            options=[ft.dropdown.Option(t.nombre) for t in tipos],
            value=tipos[0].nombre if tipos else None,
            expand=True,
        )
        txt_error    = ft.Text("", color=ft.Colors.RED_700, size=11)

        def guardar(_):
            # Validaciones
            if not tf_nombre.value or not tf_apellido.value:
                txt_error.value = "Nombre y apellido son obligatorios."
                txt_error.update(); return
            if not dd_tipo.value:
                txt_error.value = "Selecciona el tipo de habitación."
                txt_error.update(); return
            try:
                entrada = datetime.strptime(tf_entrada.value, "%Y-%m-%d").date()
                salida  = datetime.strptime(tf_salida.value,  "%Y-%m-%d").date()
                if salida <= entrada:
                    txt_error.value = "La fecha de salida debe ser posterior a la entrada."
                    txt_error.update(); return
            except ValueError:
                txt_error.value = "Fechas inválidas. Usa formato YYYY-MM-DD."
                txt_error.update(); return

            sesion = SesionLocal()
            try:
                nueva = Reservacion(
                    nombre          = tf_nombre.value.strip(),
                    apellido        = tf_apellido.value.strip(),
                    documento       = tf_doc.value.strip() or None,
                    telefono        = tf_tel.value.strip() or None,
                    email           = tf_email.value.strip() or None,
                    nacionalidad    = tf_nac.value.strip() or None,
                    tipo_habitacion = dd_tipo.value,
                    fecha_entrada   = entrada,
                    fecha_salida    = salida,
                    num_huespedes   = int(tf_huespedes.value or 1),
                    notas           = tf_notas.value.strip() or None,
                    estado          = EstadoReservacion.PENDIENTE,
                    origen          = "sistema",
                )
                sesion.add(nueva)
                sesion.flush()
                _bita(
                    sesion    = sesion,
                    pagina    = self.pagina,
                    tipo      = TipoEvento.RESERVACION,
                    concepto  = (f"Reservación — {nueva.nombre} {nueva.apellido} · "
                                 f"{nueva.tipo_habitacion} · "
                                 f"{entrada.strftime('%d/%m/%Y')} → "
                                 f"{salida.strftime('%d/%m/%Y')}"),
                )
                sesion.commit()
                self.pagina.close(dlg)
                self._refrescar()
                self.pagina.open(ft.SnackBar(
                    ft.Text("Reservación creada correctamente"),
                    bgcolor=ft.Colors.GREEN_700,
                ))
            except Exception as e:
                sesion.rollback()
                txt_error.value = str(e)
                txt_error.update()
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.EVENT_AVAILABLE, color=ft.Colors.BLUE_700),
                ft.Text("Nueva Reservación", size=16, weight="bold"),
            ], spacing=8),
            content=ft.Container(
                width=520,
                content=ft.Column([
                    ft.Text("Datos del titular", size=11, weight="bold",
                            color=ft.Colors.GREY_600),
                    ft.Row([tf_nombre, tf_apellido], spacing=10),
                    ft.Row([tf_doc, tf_tel], spacing=10),
                    ft.Row([tf_email, tf_nac], spacing=10),
                    ft.Divider(height=8),
                    ft.Text("Reservación", size=11, weight="bold",
                            color=ft.Colors.GREY_600),
                    dd_tipo,
                    ft.Row([tf_entrada, tf_salida, tf_huespedes], spacing=10),
                    tf_notas,
                    txt_error,
                ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
                height=420,
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton(
                    "Guardar reservación",
                    icon=ft.Icons.SAVE,
                    bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
                    on_click=guardar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES
    # ─────────────────────────────────────────────────────────────────────────

    def _confirmar(self, reserva_id: int):
        sesion = SesionLocal()
        try:
            r = sesion.get(Reservacion, reserva_id)
            r.estado        = EstadoReservacion.CONFIRMADA
            r.confirmado_en = datetime.now()
            _bita(sesion=sesion, pagina=self.pagina, tipo=TipoEvento.RESERVACION,
                  concepto=f"Reservación CONFIRMADA — {r.nombre} {r.apellido}")
            sesion.commit()
            self._refrescar()
            self.pagina.open(ft.SnackBar(
                ft.Text("Reservación confirmada"), bgcolor=ft.Colors.BLUE_700,
            ))
        except Exception as e:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(ft.Text(str(e)),
                                          bgcolor=ft.Colors.RED_700))
        finally:
            sesion.close()

    def _cancelar(self, reserva_id: int):
        def ejecutar(_):
            self.pagina.close(dlg)
            sesion = SesionLocal()
            try:
                r = sesion.get(Reservacion, reserva_id)
                r.estado = EstadoReservacion.CANCELADA
                _bita(sesion=sesion, pagina=self.pagina,
                      tipo=TipoEvento.RESERVACION,
                      concepto=f"Reservación CANCELADA — {r.nombre} {r.apellido}")
                sesion.commit()
                self._refrescar()
            except Exception as e:
                sesion.rollback()
                self.pagina.open(ft.SnackBar(ft.Text(str(e)),
                                              bgcolor=ft.Colors.RED_700))
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("¿Cancelar reservación?"),
            content=ft.Text("Esta acción no se puede deshacer.",
                            color=ft.Colors.GREY_600),
            actions=[
                ft.TextButton("Volver",
                              on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton("Sí, cancelar",
                                  bgcolor=ft.Colors.RED_700,
                                  color=ft.Colors.WHITE,
                                  on_click=ejecutar),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _convertir_checkin(self, reserva: Reservacion):
        """
        Convierte la reservación en check-in.
        Abre el diálogo de check-in pre-rellenado con los datos de la reservación.
        Permite asignar la habitación concreta.
        """
        from modules.rooms.checkin_reservacion import DialogoCheckInReservacion
        DialogoCheckInReservacion(
            pagina    = self.pagina,
            reserva   = reserva,
            al_completar = self._refrescar,
        ).mostrar()

    def _sheet_id_guardado(self) -> bool:
        """Devuelve True si ya hay un Sheet ID guardado en la BD."""
        from modules.rooms.importar_reservaciones import leer_config
        sesion = SesionLocal()
        try:
            return bool(leer_config(sesion)["sheet_id"])
        finally:
            sesion.close()

    def _importar_directo(self):
        """Importa sin abrir diálogo — usa la config ya guardada."""
        from modules.rooms.importar_reservaciones import importar, leer_config
        sesion = SesionLocal()
        cfg = leer_config(sesion)
        sesion.close()

        # Mostrar indicador
        self.pagina.open(ft.SnackBar(
            ft.Text("⏳ Importando desde Google Sheets..."),
            bgcolor=ft.Colors.BLUE_700,
        ))

        res = importar(cfg["sheet_id"], cfg["script_url"])

        if res["importadas"] == 0 and res["errores"] == 0:
            msg = "ℹ No hay reservaciones nuevas."
            color = ft.Colors.BLUE_GREY_600
        elif res["errores"] == 0:
            msg = f"✅ {res['importadas']} reservación(es) importada(s)."
            color = ft.Colors.GREEN_700
        else:
            msg = (f"⚠ {res['importadas']} importada(s), "
                   f"{res['errores']} error(es).")
            color = ft.Colors.ORANGE_700

        self.pagina.open(ft.SnackBar(ft.Text(msg), bgcolor=color))
        self._refrescar()

    def _dlg_importar(self):
        """Diálogo para configurar la Sheet e importar reservaciones web."""
        from modules.rooms.importar_reservaciones import importar, leer_config, guardar_config

        sesion = SesionLocal()
        cfg    = leer_config(sesion)
        sesion.close()

        tf_sheet = ft.TextField(
            label="Google Sheet ID",
            value=cfg["sheet_id"],
            hint_text="El código largo en la URL de la Sheet",
            expand=True,
        )
        tf_script = ft.TextField(
            label="URL del Apps Script (opcional)",
            value=cfg["script_url"],
            hint_text="https://script.google.com/macros/s/.../exec",
            expand=True,
        )
        txt_res = ft.Text("", size=12)

        def ejecutar(_):
            sid = tf_sheet.value.strip()
            if not sid:
                txt_res.value = "⚠ El Sheet ID es obligatorio."
                txt_res.color = ft.Colors.ORANGE_700
                txt_res.update(); return

            # Guardar configuración
            s2 = SesionLocal()
            try:
                guardar_config(s2, sid, tf_script.value.strip())
                s2.commit()
            finally:
                s2.close()

            txt_res.value = "⏳ Conectando con Google Sheets..."
            txt_res.color = ft.Colors.BLUE_700
            txt_res.update()

            res = importar(sid, tf_script.value.strip())

            if res["errores"] == 0:
                txt_res.value = (
                    f"✅ {res['importadas']} reservación(es) importada(s)."
                    if res["importadas"] > 0
                    else "ℹ No hay reservaciones nuevas por importar."
                )
                txt_res.color = ft.Colors.GREEN_700
            else:
                txt_res.value = (
                    f"⚠ {res['importadas']} importada(s) · "
                    f"{res['errores']} error(es): "
                    + "; ".join(res["detalle_errores"][:3])
                )
                txt_res.color = ft.Colors.ORANGE_700
            txt_res.update()
            self._refrescar()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.CLOUD_DOWNLOAD, color=ft.Colors.PURPLE_700),
                ft.Text("Importar desde Google Sheets", size=15, weight="bold"),
            ], spacing=8),
            content=ft.Container(
                width=500,
                content=ft.Column([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("① Sheet ID", size=11, weight="bold",
                                    color=ft.Colors.GREY_700),
                            ft.Text(
                                "Está en la URL de la hoja:\n"
                                "docs.google.com/spreadsheets/d/ → ID ← /edit",
                                size=11, color=ft.Colors.GREY_500,
                            ),
                            tf_sheet,
                        ], spacing=6),
                        bgcolor=ft.Colors.GREY_50, border_radius=8,
                        padding=12,
                        border=ft.border.all(1, ft.Colors.GREY_200),
                    ),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("② URL del Apps Script (opcional)",
                                    size=11, weight="bold", color=ft.Colors.GREY_700),
                            ft.Text(
                                "Si la configuras, las filas importadas se marcan "
                                "automáticamente en la Sheet para no duplicar.",
                                size=11, color=ft.Colors.GREY_500,
                            ),
                            tf_script,
                        ], spacing=6),
                        bgcolor=ft.Colors.GREY_50, border_radius=8,
                        padding=12,
                        border=ft.border.all(1, ft.Colors.GREY_200),
                    ),
                    txt_res,
                ], spacing=12, tight=True),
            ),
            actions=[
                ft.TextButton("Cerrar",
                              on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton(
                    "Importar ahora",
                    icon=ft.Icons.DOWNLOAD,
                    bgcolor=ft.Colors.PURPLE_700, color=ft.Colors.WHITE,
                    on_click=ejecutar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)

    def _toggle_filtro(self):
        self._filtro = "todas" if self._filtro == "activas" else "activas"
        self._refrescar()

    def _refrescar(self):
        self._construir()
        self.update()
        if self.al_actualizar:
            self.al_actualizar()