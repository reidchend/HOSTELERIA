# modules/finance/pantalla_bitacora.py
"""
Vista de la bitácora del turno activo.

Muestra un log cronológico de todos los eventos del turno en curso,
con filtros por tipo y opción de agregar notas libres.
Se actualiza en tiempo real (botón refrescar).
"""

import flet as ft
from datetime import datetime
from decimal import Decimal
from database.connection import SesionLocal
from database.models import BitacoraEvento, TipoEvento, Turno, Usuario
from modules.finance.bitacora import registrar
from utils.calculos_financieros import a_bs


# ── Configuración visual por tipo de evento ──────────────────────────────────
CFG_TIPO = {
    TipoEvento.CHECKIN:     ("CHKIN",  ft.Icons.LOGIN,              ft.Colors.GREEN_700),
    TipoEvento.CHECKOUT:    ("CHKOUT", ft.Icons.LOGOUT,             ft.Colors.RED_700),
    TipoEvento.PAGO:        ("PAGO",   ft.Icons.PAYMENTS,           ft.Colors.BLUE_700),
    TipoEvento.CARGO_EXTRA: ("CARGO",  ft.Icons.ROOM_SERVICE,       ft.Colors.ORANGE_700),
    TipoEvento.VUELTO:      ("VUELTO", ft.Icons.CURRENCY_EXCHANGE,  ft.Colors.AMBER_800),
    TipoEvento.RENOVACION:  ("RENOV",  ft.Icons.AUTORENEW,          ft.Colors.TEAL_700),
    TipoEvento.RESERVACION: ("RESRV",  ft.Icons.EVENT_AVAILABLE,    ft.Colors.PURPLE_700),
    TipoEvento.CAJA:        ("CAJA",   ft.Icons.ACCOUNT_BALANCE,    ft.Colors.INDIGO_700),
    TipoEvento.NOTA:        ("NOTA",   ft.Icons.STICKY_NOTE_2,      ft.Colors.BROWN_600),
    TipoEvento.SISTEMA:     ("SYS",    ft.Icons.SETTINGS,           ft.Colors.GREY_600),
}


class PantallaBitacora(ft.Container):

    def __init__(self, pagina: ft.Page, estado_app: dict):
        super().__init__()
        self.pagina     = pagina
        self.estado_app = estado_app
        self.expand     = True
        self.padding    = ft.padding.symmetric(horizontal=28, vertical=20)

        # Filtro activo (None = todos)
        self._filtro: TipoEvento | None = None

        self._construir()

    # ─────────────────────────────────────────────────────────────────────────
    # DATOS
    # ─────────────────────────────────────────────────────────────────────────

    def _turno_activo(self):
        """Devuelve (turno_id, nombre_recepcionista, hora_inicio) del turno activo."""
        try:
            tid = self.pagina.session.get("id_turno_actual")
            if not tid:
                return None, "—", None
            sesion = SesionLocal()
            try:
                t = sesion.get(Turno, tid)
                if not t:
                    return None, "—", None
                u = sesion.get(Usuario, t.usuario_id)
                nombre = u.nombre_completo if u else "—"
                return tid, nombre, t.hora_inicio
            finally:
                sesion.close()
        except Exception:
            return None, "—", None

    def _cargar_eventos(self, turno_id: int) -> list:
        sesion = SesionLocal()
        try:
            q = sesion.query(BitacoraEvento).filter(
                BitacoraEvento.turno_id == turno_id
            )
            if self._filtro:
                q = q.filter(BitacoraEvento.tipo == self._filtro)
            return q.order_by(BitacoraEvento.creado_en.desc()).all()
        finally:
            sesion.close()

    def _resumen_turno(self, turno_id: int) -> dict:
        sesion = SesionLocal()
        try:
            evts = sesion.query(BitacoraEvento).filter(
                BitacoraEvento.turno_id == turno_id
            ).all()
            total_cobrado = sum(
                float(e.monto_usd) for e in evts
                if e.tipo == TipoEvento.PAGO
            )
            total_vueltos = sum(
                float(e.monto_usd) for e in evts
                if e.tipo == TipoEvento.VUELTO
            )
            n_checkins  = sum(1 for e in evts if e.tipo == TipoEvento.CHECKIN)
            n_checkouts = sum(1 for e in evts if e.tipo == TipoEvento.CHECKOUT)
            pendientes  = sum(1 for e in evts if not e.confirmado)
            return {
                "cobrado":    total_cobrado,
                "vueltos":    total_vueltos,
                "neto":       total_cobrado - total_vueltos,
                "checkins":   n_checkins,
                "checkouts":  n_checkouts,
                "pendientes": pendientes,
                "total":      len(evts),
            }
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN
    # ─────────────────────────────────────────────────────────────────────────

    def _construir(self):
        turno_id, recepcionista, hora_inicio = self._turno_activo()

        if not turno_id:
            self.content = ft.Column([
                ft.Icon(ft.Icons.HISTORY_TOGGLE_OFF,
                        size=48, color=ft.Colors.GREY_400),
                ft.Text("No hay turno activo",
                        size=16, color=ft.Colors.GREY_500),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               alignment=ft.MainAxisAlignment.CENTER,
               expand=True)
            return

        eventos  = self._cargar_eventos(turno_id)
        resumen  = self._resumen_turno(turno_id)
        tasa     = self.estado_app.get("tasa_cambio", 1.0)

        # ── Encabezado ────────────────────────────────────────────────────────
        duracion = ""
        if hora_inicio:
            mins = int((datetime.now() - hora_inicio).total_seconds() / 60)
            h, m = divmod(mins, 60)
            duracion = f"{h}h {m}m"

        encabezado = ft.Row([
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.HISTORY, color=ft.Colors.BLUE_700, size=20),
                    ft.Text("Bitácora del Turno", size=22, weight="bold",
                            color=ft.Colors.BLUE_GREY_900),
                ], spacing=8),
                ft.Text(
                    f"Recepcionista: {recepcionista}  ·  "
                    f"Inicio: {hora_inicio.strftime('%d/%m/%Y %H:%M') if hora_inicio else '—'}"
                    f"  ·  Duración: {duracion}",
                    size=12, color=ft.Colors.GREY_600,
                ),
            ], spacing=3, expand=True),
            ft.Row([
                ft.ElevatedButton(
                    "Refrescar",
                    icon=ft.Icons.REFRESH,
                    bgcolor=ft.Colors.BLUE_50, color=ft.Colors.BLUE_800,
                    style=ft.ButtonStyle(
                        side=ft.BorderSide(1, ft.Colors.BLUE_300),
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                    on_click=lambda _: self._refrescar(),
                ),
                ft.ElevatedButton(
                    "Agregar Nota",
                    icon=ft.Icons.ADD_COMMENT,
                    bgcolor=ft.Colors.AMBER_50, color=ft.Colors.AMBER_900,
                    style=ft.ButtonStyle(
                        side=ft.BorderSide(1, ft.Colors.AMBER_300),
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                    on_click=lambda _: self._dlg_nota(turno_id),
                ),
            ], spacing=10),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # ── Tarjetas de resumen ───────────────────────────────────────────────
        def chip_resumen(valor, label, color):
            return ft.Container(
                content=ft.Column([
                    ft.Text(str(valor), size=18, weight="bold", color=color),
                    ft.Text(label, size=10, color=ft.Colors.GREY_500),
                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1.5, ft.Colors.with_opacity(0.35, color)),
                border_radius=10, padding=ft.padding.symmetric(horizontal=18, vertical=10),
            )

        fila_resumen = ft.Row([
            chip_resumen(f"${resumen['cobrado']:,.2f}", "Cobrado", ft.Colors.GREEN_700),
            chip_resumen(f"${resumen['vueltos']:,.2f}", "Vueltos", ft.Colors.ORANGE_700),
            chip_resumen(f"${resumen['neto']:,.2f}",    "Neto",    ft.Colors.BLUE_700),
            chip_resumen(resumen["checkins"],   "Check-ins",  ft.Colors.TEAL_700),
            chip_resumen(resumen["checkouts"],  "Check-outs", ft.Colors.RED_700),
            chip_resumen(resumen["pendientes"], "Pendientes", ft.Colors.AMBER_800),
            chip_resumen(resumen["total"],      "Eventos",    ft.Colors.GREY_600),
        ], spacing=8, wrap=True)

        # ── Filtros por tipo ──────────────────────────────────────────────────
        def btn_filtro(tipo: TipoEvento | None, label: str, color):
            activo = self._filtro == tipo
            return ft.ElevatedButton(
                text=label,
                style=ft.ButtonStyle(
                    bgcolor=color if activo else ft.Colors.GREY_100,
                    color=ft.Colors.WHITE if activo else ft.Colors.GREY_700,
                    shape=ft.RoundedRectangleBorder(radius=20),
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                ),
                on_click=lambda _, t=tipo: self._set_filtro(t),
                height=32,
            )

        filtros = ft.Row([
            btn_filtro(None, "Todos", ft.Colors.BLUE_GREY_600),
            btn_filtro(TipoEvento.CHECKIN,     "Check-in",   ft.Colors.GREEN_700),
            btn_filtro(TipoEvento.CHECKOUT,    "Check-out",  ft.Colors.RED_700),
            btn_filtro(TipoEvento.PAGO,        "Pagos",      ft.Colors.BLUE_700),
            btn_filtro(TipoEvento.CARGO_EXTRA, "Cargos",     ft.Colors.ORANGE_700),
            btn_filtro(TipoEvento.VUELTO,      "Vueltos",    ft.Colors.AMBER_800),
            btn_filtro(TipoEvento.RENOVACION,  "Renov.",     ft.Colors.TEAL_700),
            btn_filtro(TipoEvento.NOTA,        "Notas",      ft.Colors.BROWN_600),
        ], spacing=6, wrap=True)

        # ── Lista de eventos ──────────────────────────────────────────────────
        if not eventos:
            lista = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.INBOX, size=40, color=ft.Colors.GREY_300),
                    ft.Text(
                        "Sin eventos" if self._filtro
                        else "El turno aún no tiene eventos registrados.",
                        size=13, color=ft.Colors.GREY_400, italic=True,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   alignment=ft.MainAxisAlignment.CENTER),
                padding=40,
            )
        else:
            lista = ft.Column(
                controls=[self._fila_evento(e, tasa) for e in eventos],
                spacing=4,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )

        self.content = ft.Column([
            encabezado,
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            fila_resumen,
            filtros,
            ft.Divider(height=1, color=ft.Colors.GREY_200),
            lista,
        ], spacing=12, expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    # FILA DE EVENTO
    # ─────────────────────────────────────────────────────────────────────────

    def _fila_evento(self, e: BitacoraEvento, tasa: float) -> ft.Container:
        etiq, icono, color = CFG_TIPO.get(
            e.tipo, ("EVT", ft.Icons.CIRCLE, ft.Colors.GREY_500)
        )

        # Badge de confirmación
        badge = ft.Container(
            content=ft.Text(
                "✓ Confirmado" if e.confirmado else "⏳ Pendiente",
                size=9, weight="bold",
                color=ft.Colors.WHITE,
            ),
            bgcolor=ft.Colors.GREEN_700 if e.confirmado else ft.Colors.ORANGE_700,
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            border_radius=8,
        )

        # Monto (solo si > 0)
        monto_usd = float(e.monto_usd or 0)
        monto_bs  = float(e.monto_bs  or 0)
        col_monto = ft.Column(spacing=0,
                              horizontal_alignment=ft.CrossAxisAlignment.END)
        if monto_usd > 0:
            col_monto.controls.append(
                ft.Text(f"${monto_usd:,.2f}", size=13, weight="bold", color=color)
            )
        if monto_bs > 0:
            col_monto.controls.append(
                ft.Text(f"Bs. {monto_bs:,.2f}", size=10, color=ft.Colors.GREY_500)
            )
        elif monto_usd > 0 and tasa:
            col_monto.controls.append(
                ft.Text(f"Bs. {a_bs(monto_usd, tasa):,.2f}",
                        size=10, color=ft.Colors.GREY_400)
            )

        # Línea de detalle (referencia / método)
        detalles = []
        if e.metodo_pago:
            detalles.append(e.metodo_pago)
        if e.referencia:
            detalles.append(e.referencia)
        if e.recepcionista:
            detalles.append(f"por {e.recepcionista}")
        detalle_txt = "  ·  ".join(detalles)

        return ft.Container(
            content=ft.Row([
                # Ícono tipo
                ft.Container(
                    content=ft.Column([
                        ft.Container(
                            content=ft.Icon(icono, size=14, color=ft.Colors.WHITE),
                            bgcolor=color, border_radius=6,
                            width=28, height=28,
                            alignment=ft.alignment.center,
                        ),
                        ft.Text(etiq, size=7, color=ft.Colors.GREY_500,
                                text_align=ft.TextAlign.CENTER),
                    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    width=36,
                ),
                # Hora
                ft.Text(
                    e.creado_en.strftime("%H:%M"),
                    size=11, color=ft.Colors.GREY_500, width=38,
                ),
                # Habitación
                ft.Container(
                    content=ft.Text(
                        f"Hab.{e.habitacion}" if e.habitacion else "",
                        size=10, weight="bold", color=color,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    width=54,
                ),
                ft.VerticalDivider(width=1, color=ft.Colors.GREY_200),
                # Concepto + detalle
                ft.Column([
                    ft.Text(e.concepto, size=12, color=ft.Colors.BLACK87,
                            expand=True),
                    ft.Text(detalle_txt, size=10, color=ft.Colors.GREY_500,
                            italic=True) if detalle_txt else ft.Container(height=0),
                ], spacing=1, expand=True),
                # Badge confirmación
                badge,
                # Monto
                col_monto,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=ft.Colors.WHITE if e.confirmado else ft.Colors.ORANGE_50,
            border=ft.border.all(
                1,
                ft.Colors.GREY_200 if e.confirmado else ft.Colors.ORANGE_200,
            ),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ACCIONES
    # ─────────────────────────────────────────────────────────────────────────

    def _set_filtro(self, tipo):
        self._filtro = tipo
        self._refrescar()

    def _refrescar(self):
        self._construir()
        self.update()

    def _dlg_nota(self, turno_id: int):
        """Diálogo para agregar una nota libre a la bitácora."""
        tf_hab  = ft.TextField(
            label="Habitación (opcional)",
            width=120, hint_text="Ej: 26",
        )
        tf_nota = ft.TextField(
            label="Nota", multiline=True,
            min_lines=2, max_lines=5,
            expand=True, autofocus=True,
            hint_text="Escribe cualquier observación del turno...",
        )

        def guardar(_):
            texto = tf_nota.value.strip()
            if not texto:
                tf_nota.error_text = "La nota no puede estar vacía"
                tf_nota.update()
                return
            sesion = SesionLocal()
            try:
                registrar(
                    sesion      = sesion,
                    pagina      = self.pagina,
                    tipo        = TipoEvento.NOTA,
                    concepto    = texto,
                    habitacion  = tf_hab.value.strip(),
                )
                sesion.commit()
                self.pagina.close(dlg)
                self._refrescar()
                self.pagina.open(ft.SnackBar(
                    ft.Text("Nota agregada a la bitácora"),
                    bgcolor=ft.Colors.GREEN_700,
                ))
            except Exception as err:
                sesion.rollback()
                self.pagina.open(ft.SnackBar(
                    ft.Text(str(err)), bgcolor=ft.Colors.RED_700,
                ))
            finally:
                sesion.close()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.STICKY_NOTE_2, color=ft.Colors.AMBER_700),
                ft.Text("Agregar Nota a la Bitácora"),
            ], spacing=8),
            content=ft.Container(
                width=420,
                content=ft.Column([
                    tf_hab,
                    tf_nota,
                ], spacing=12, tight=True),
            ),
            actions=[
                ft.TextButton("Cancelar",
                              on_click=lambda _: self.pagina.close(dlg)),
                ft.ElevatedButton(
                    "Guardar Nota",
                    icon=ft.Icons.SAVE,
                    bgcolor=ft.Colors.AMBER_700, color=ft.Colors.WHITE,
                    on_click=guardar,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg)