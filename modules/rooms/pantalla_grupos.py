# modules/rooms/pantalla_grupos.py

import flet as ft
from database.connection import SesionLocal
from database.models import (
    GrupoHabitacion, 
    Habitacion, 
    Estadia, 
    Huesped,
    LedgerMovimiento,
    FolioLinea,
    EstadoHabitacion,
    TipoMovimiento,
    TipoLinea,
)
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from modules.finance.payment_dialog import DialogoPago
from utils.calculos_financieros import leer_config_financiera, a_bs


class PantallaGrupos(ft.Container):
    def __init__(self, pagina: ft.Page, estado_app: dict, al_volver=None):
        super().__init__()
        self.pagina = pagina
        self.estado_app = estado_app
        self.al_volver = al_volver
        self.grupos = []
        self._sesion = None
        self.expand = True
        self.bgcolor = ft.Colors.SURFACE
        self.padding = 0
        
        self.content = self._crear_contenido()

    def _crear_contenido(self):
        btn_volver = ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            on_click=lambda _: self._volver(),
        )
        
        titulo = ft.Text(
            "Gestión de Grupos",
            size=24,
            weight=ft.FontWeight.BOLD,
        )
        
        self.lista_grupos = ft.ListView(
            expand=True,
            spacing=10,
            padding=20,
        )
        
        self.btn_actualizar = ft.ElevatedButton(
            "Actualizar",
            icon=ft.Icons.REFRESH,
            on_click=lambda _: self._cargar_grupos(),
        )
        
        return ft.Column([
            ft.Container(
                content=ft.Row([btn_volver, titulo], spacing=10),
                padding=ft.padding.all(20),
                border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.OUTLINE)),
            ),
            self.lista_grupos,
            ft.Container(
                content=self.btn_actualizar,
                alignment=ft.alignment.center,
                padding=20,
            ),
        ], spacing=0, expand=True)

    def _volver(self):
        if self.al_volver:
            self.al_volver()

    def _cargar_grupos(self):
        self._sesion = SesionLocal()
        try:
            self.grupos = (
                self._sesion.query(GrupoHabitacion)
                .options(
                    selectinload(GrupoHabitacion.habitaciones),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.habitacion),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.ledger_movimientos),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.folio_lineas),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.huespedes),
                    selectinload(GrupoHabitacion.huesped_principal),
                )
                .all()
            )
            self._actualizar_lista()
        except Exception as e:
            print(f"Error cargando grupos: {e}")
        finally:
            if self._sesion:
                self._sesion.close()
                self._sesion = None

    def _actualizar_lista(self):
        self.lista_grupos.controls = []
        
        if not self.grupos:
            self.lista_grupos.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.GROUP_WORK_OUTLINED, size=64, color="#6B7280"),
                        ft.Text("No hay grupos creados", size=16, color="#6B7280"),
                        ft.Text("Seleccione habitaciones del dashboard y cree un grupo", size=12, color="#6B7280"),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.alignment.center,
                    padding=50,
                )
            )
            self.update()
            return
        
        for grupo in self.grupos:
            tarjeta = self._crear_tarjeta_grupo(grupo)
            self.lista_grupos.controls.append(tarjeta)
        
        self.update()

    def _calcular_saldos_grupo(self, grupo):
        """Calcula los saldos consolidados del grupo."""
        total_cargos = 0.0
        total_pagos = 0.0
        total_saldo_favor = 0.0
        estadias_con_deuda = []
        estadias_con_saldo_favor = []
        
        for est in grupo.estadias:
            debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
            haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
            saldo = debe - haber
            
            if saldo > 0.01:
                estadias_con_deuda.append({"estadia": est, "saldo": saldo})
                total_cargos += saldo
            elif saldo < -0.01:
                estadias_con_saldo_favor.append({"estadia": est, "saldo": abs(saldo)})
                total_saldo_favor += abs(saldo)
            
            total_pagos += haber
        
        # Verificar crédito de huéspedes
        for est in grupo.estadias:
            for huesped in est.huespedes:
                if huesped.credito_usd and float(huesped.credito_usd) > 0:
                    total_saldo_favor += float(huesped.credito_usd)
        
        return {
            "total_cargos": total_cargos,
            "total_pagos": total_pagos,
            "total_saldo_favor": total_saldo_favor,
            "saldo_neto": total_cargos - total_saldo_favor,
            "estadias_con_deuda": estadias_con_deuda,
            "estadias_con_saldo_favor": estadias_con_saldo_favor,
        }

    def _crear_tarjeta_grupo(self, grupo):
        habs_activas = [h for h in grupo.habitaciones if h.estado == EstadoHabitacion.OCCUPIED]
        saldos = self._calcular_saldos_grupo(grupo)
        
        hab_numeros = ", ".join([h.numero for h in grupo.habitaciones])
        color_grupo = grupo.color_etiqueta or "#8B5CF6"
        
        nombre_principal = ""
        if grupo.huesped_principal:
            nombre_principal = f"{grupo.huesped_principal.nombre} {grupo.huesped_principal.apellido}"
        
        # Determinar color del saldo
        if saldos["saldo_neto"] > 0.01:
            saldo_color = ft.Colors.ERROR
            saldo_icon = ft.Icons.ARROW_UPWARD
            saldo_label = "DEUDA"
        elif saldos["saldo_neto"] < -0.01:
            saldo_color = ft.Colors.GREEN_700
            saldo_icon = ft.Icons.ARROW_DOWNWARD
            saldo_label = "SALDO A FAVOR"
        else:
            saldo_color = ft.Colors.BLUE_700
            saldo_icon = ft.Icons.CHECK_CIRCLE
            saldo_label = "SALDADO"
        
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Container(width=8, height=40, bgcolor=color_grupo, border_radius=4),
                        ft.Column([
                            ft.Text(grupo.nombre, size=18, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Habitaciones: {hab_numeros}", size=12, color="#6B7280"),
                        ], spacing=2),
                    ], spacing=10),
                    margin=ft.margin.only(bottom=10),
                ),
                
                # Resumen financiero
                ft.Container(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Total Cargos", size=9, color="#6B7280"),
                                ft.Text(f"${saldos['total_cargos']:.2f}", size=16, weight=ft.FontWeight.BOLD),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=1,
                        ),
                        ft.VerticalDivider(),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Total Pagos", size=9, color="#6B7280"),
                                ft.Text(f"${saldos['total_pagos']:.2f}", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=1,
                        ),
                        ft.VerticalDivider(),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Saldo", size=9, color="#6B7280"),
                                ft.Row([
                                    ft.Icon(saldo_icon, size=14, color=saldo_color),
                                    ft.Text(f"${abs(saldos['saldo_neto']):.2f}", size=16, weight=ft.FontWeight.BOLD, color=saldo_color),
                                ], spacing=2),
                                ft.Text(saldo_label, size=8, color=saldo_color),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            expand=1,
                        ),
                    ], spacing=5),
                    padding=10,
                    bgcolor="#F3F4F6",
                    border_radius=8,
                ),
                
                # Info adicional
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Hab. Ocupadas", size=9, color="#6B7280"),
                            ft.Text(f"{len(habs_activas)}/{len(grupo.habitaciones)}", size=14, weight=ft.FontWeight.BOLD),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=1,
                    ),
                    ft.VerticalDivider(),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Huésped Principal", size=9, color="#6B7280"),
                            ft.Text(nombre_principal or "No asignado", size=12, overflow=ft.TextOverflow.ELLIPSIS),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=2,
                    ),
                ], spacing=5),
                
                # Botones de acción
                ft.Row([
                    ft.ElevatedButton(
                        "Ver Detalles",
                        icon=ft.Icons.VISIBILITY,
                        on_click=lambda e, g=grupo: self._ver_detalles(g),
                    ),
                    ft.ElevatedButton(
                        "Cobrar Todo",
                        icon=ft.Icons.PAYMENT,
                        bgcolor=ft.Colors.PRIMARY,
                        color=ft.Colors.ON_PRIMARY,
                        on_click=lambda e, g=grupo: self._cobrar_grupo(g),
                    ),
                    ft.ElevatedButton(
                        "Cobrar Selección",
                        icon=ft.Icons.SELECT_ALL,
                        bgcolor=ft.Colors.AMBER_700,
                        color=ft.Colors.ON_PRIMARY,
                        on_click=lambda e, g=grupo: self._cobrar_seleccion(g),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="Eliminar grupo",
                        on_click=lambda e, g=grupo: self._eliminar_grupo(g),
                    ),
                ], spacing=5),
            ], spacing=10),
            padding=20,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=12,
        )

    def _ver_detalles(self, grupo):
        sesion = SesionLocal()
        try:
            grupo_fresh = (
                sesion.query(GrupoHabitacion)
                .options(
                    selectinload(GrupoHabitacion.habitaciones),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.habitacion),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.ledger_movimientos),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.folio_lineas),
                    selectinload(GrupoHabitacion.estadias)
                        .selectinload(Estadia.huespedes),
                )
                .filter(GrupoHabitacion.id == grupo.id)
                .first()
            )
            if not grupo_fresh:
                self.pagina.open(ft.SnackBar(content=ft.Text("Grupo no encontrado")))
                return
            
            saldos = self._calcular_saldos_grupo(grupo_fresh)
            
            contenido = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
            
            # Resumen financiero
            contenido.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("Resumen Financiero", size=16, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.Column([
                                ft.Text("Cargos", size=10, color="#6B7280"),
                                ft.Text(f"${saldos['total_cargos']:.2f}", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ERROR),
                            ]),
                            ft.Column([
                                ft.Text("Pagos", size=10, color="#6B7280"),
                                ft.Text(f"${saldos['total_pagos']:.2f}", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
                            ]),
                            ft.Column([
                                ft.Text("Saldo Neto", size=10, color="#6B7280"),
                                ft.Text(f"${saldos['saldo_neto']:.2f}", size=18, weight=ft.FontWeight.BOLD, 
                                       color=ft.Colors.ERROR if saldos['saldo_neto'] > 0 else ft.Colors.GREEN_700),
                            ]),
                        ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                    ], spacing=5),
                    padding=15,
                    bgcolor="#F3F4F6",
                    border_radius=8,
                )
            )
            
            # Habitaciones
            contenido.controls.append(ft.Divider())
            contenido.controls.append(
                ft.Text("Habitaciones del Grupo", size=14, weight=ft.FontWeight.BOLD)
            )
            
            for hab in grupo_fresh.habitaciones:
                estado_color = ft.Colors.GREEN_700 if hab.estado == EstadoHabitacion.FREE else ft.Colors.RED_700
                contenido.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(f"Hab. {hab.numero}", weight=ft.FontWeight.BOLD),
                            ft.Text(f"({hab.tipo})", color="#6B7280"),
                            ft.Container(
                                content=ft.Text(str(hab.estado.value), size=10),
                                bgcolor=estado_color,
                                padding=ft.padding.symmetric(horizontal=8, vertical=2),
                                border_radius=10,
                            ),
                        ]),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                    )
                )
            
            # Estadías con desglose
            contenido.controls.append(ft.Divider())
            contenido.controls.append(
                ft.Text("Detalle por Habitación", size=14, weight=ft.FontWeight.BOLD)
            )
            
            for est in grupo_fresh.estadias:
                if not est.activa:
                    continue
                
                debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
                haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                saldo = debe - haber
                
                huesped_nombres = ", ".join([h.nombre_completo for h in est.huespedes[:2]])
                
                # Líneas de folio
                lineas_detalle = []
                for linea in est.folio_lineas:
                    if not linea.cancelada:
                        lineas_detalle.append(
                            ft.Row([
                                ft.Text(f"• {linea.concepto}", size=11, expand=True),
                                ft.Text(f"${float(linea.total_usd):.2f}", size=11, weight=ft.FontWeight.BOLD),
                            ])
                        )
                
                # Movimientos de pago
                pagos_detalle = []
                for mov in est.ledger_movimientos:
                    if mov.tipo == TipoMovimiento.PAGO:
                        pagos_detalle.append(
                            ft.Row([
                                ft.Text(f"✓ {mov.concepto}", size=11, expand=True),
                                ft.Text(f"-${float(mov.haber_usd):.2f}", size=11, color=ft.Colors.GREEN_700),
                            ])
                        )
                
                contenido.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(f"Hab. {est.habitacion.numero}", weight=ft.FontWeight.BOLD),
                                ft.Text(f"Saldo: ${saldo:.2f}", size=12, weight=ft.FontWeight.BOLD,
                                       color=ft.Colors.ERROR if saldo > 0 else ft.Colors.GREEN_700),
                            ]),
                            ft.Text(f"Huéspedes: {huesped_nombres}", size=11),
                            ft.Text(f"Entrada: {est.entrada.strftime('%d/%m/%Y %H:%M')}", size=11),
                            ft.Divider(height=5),
                            ft.Text("Cargos:", size=10, weight=ft.FontWeight.BOLD),
                        ] + lineas_detalle + [
                            ft.Divider(height=5),
                            ft.Text("Pagos:", size=10, weight=ft.FontWeight.BOLD),
                        ] + pagos_detalle, spacing=2),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                    )
                )
            
            dlg = ft.AlertDialog(
                title=ft.Text(f"Detalles: {grupo_fresh.nombre}"),
                content=ft.Container(content=contenido, width=550, height=500),
                actions=[ft.TextButton("Cerrar", on_click=lambda _: self.pagina.close(dlg))],
            )
            self.pagina.open(dlg)
        finally:
            sesion.close()

    def _cobrar_grupo(self, grupo):
        """Cobra TODA la deuda del grupo."""
        saldos = self._calcular_saldos_grupo(grupo)
        estadias_con_deuda = saldos["estadias_con_deuda"]
        
        if not estadias_con_deuda:
            self.pagina.open(ft.SnackBar(content=ft.Text("No hay deuda pendiente en este grupo")))
            return
        
        total_deuda = saldos["saldo_neto"]
        
        # Recargar con sesión fresca para el pago
        sesion = SesionLocal()
        try:
            estadias_frescas = (
                sesion.query(Estadia)
                .options(
                    selectinload(Estadia.habitacion),
                    selectinload(Estadia.ledger_movimientos),
                    selectinload(Estadia.folio_lineas),
                    selectinload(Estadia.huespedes),
                )
                .filter(Estadia.grupo_id == grupo.id, Estadia.activa == True)
                .all()
            )
            
            # Obtener todas las líneas de folio pendientes
            lineas_ids = []
            for est in estadias_frescas:
                for linea in est.folio_lineas:
                    if not linea.cancelada:
                        lineas_ids.append(linea.id)
            
            primera_estadia = estadias_frescas[0] if estadias_frescas else None
            
            dlg_pago = DialogoPago(
                self.pagina,
                primera_estadia,
                total_deuda,
                al_completar=lambda: self._cargar_grupos(),
                lineas_ids=lineas_ids,
                checkin_info={
                    "habitacion": f"Grupo {grupo.nombre}",
                    "monto": total_deuda,
                    "nombre": grupo.huesped_principal.nombre_completo if grupo.huesped_principal else "",
                    "noches": 1,
                    "fecha_salida": "",
                    "es_grupo": True,
                    "total_habitaciones": len(estadias_frescas),
                    "nombre_grupo": grupo.nombre,
                    "habitaciones_data": [{"numero": est.habitacion.numero} for est in estadias_frescas if est.habitacion],
                },
            )
            dlg_pago.mostrar()
        finally:
            sesion.close()

    def _cobrar_seleccion(self, grupo):
        """Abre diálogo para seleccionar qué cargos cobrar de cada habitación."""
        sesion = SesionLocal()
        try:
            estadias_frescas = (
                sesion.query(Estadia)
                .options(
                    selectinload(Estadia.habitacion),
                    selectinload(Estadia.folio_lineas),
                    selectinload(Estadia.huespedes),
                )
                .filter(Estadia.grupo_id == grupo.id, Estadia.activa == True)
                .all()
            )
            
            if not estadias_frescas:
                self.pagina.open(ft.SnackBar(content=ft.Text("No hay estadías activas en este grupo")))
                return
            
            self._mostrar_dialogo_seleccion(grupo, estadias_frescas)
        finally:
            sesion.close()

    def _mostrar_dialogo_seleccion(self, grupo, estadias):
        """Diálogo con checkboxes para seleccionar cargos por habitación."""
        checkboxes_por_hab = {}  # {hab_id: {linea_id: (checkbox, monto)}}
        contenido = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10)
        
        for est in estadias:
            lineas_pendientes = [l for l in est.folio_lineas if not l.cancelada]
            if not lineas_pendientes:
                continue
            
            total_hab = sum(float(l.total_usd) for l in lineas_pendientes)
            checkboxes_por_hab[est.habitacion_id] = {}
            
            # Encabezado de habitación
            contenido.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(f"Hab. {est.habitacion.numero}", size=14, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Total: ${total_hab:.2f}", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ERROR),
                            ft.Container(expand=True),
                            ft.TextButton("Marcar todas", icon=ft.Icons.CHECK_BOX_OUTLINED, 
                                         on_click=lambda e, hid=est.habitacion_id: self._marcar_todos(checkboxes_por_hab[hid], True)),
                            ft.TextButton("Desmarcar", icon=ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                                         on_click=lambda e, hid=est.habitacion_id: self._marcar_todos(checkboxes_por_hab[hid], False)),
                        ]),
                    ], spacing=5),
                    padding=10,
                    bgcolor="#F3F4F6",
                    border_radius=8,
                )
            )
            
            # Líneas de folio
            for linea in lineas_pendientes:
                cb = ft.Checkbox(value=True, label="", on_change=lambda _: self._actualizar_total_seleccionado(checkboxes_por_hab, texto_total_sel))
                checkboxes_por_hab[est.habitacion_id][linea.id] = (cb, float(linea.total_usd))
                
                tipo_cfg = {
                    TipoLinea.HOSPEDAJE: (ft.Icons.BED_OUTLINED, ft.Colors.BLUE_700, "Hospedaje"),
                    TipoLinea.CARGO_EXTRA: (ft.Icons.ROOM_SERVICE, ft.Colors.ORANGE_700, "Servicio"),
                    TipoLinea.SALDO_PENDIENTE: (ft.Icons.PENDING_ACTIONS, ft.Colors.RED_700, "Deuda anterior"),
                }
                icono, color, etiqueta = tipo_cfg.get(linea.tipo, (ft.Icons.CIRCLE, ft.Colors.GREY_500, "Otro"))
                
                contenido.controls.append(
                    ft.Container(
                        content=ft.Row([
                            cb,
                            ft.Icon(icono, size=15, color=color),
                            ft.Column([
                                ft.Text(linea.concepto, size=11, weight=ft.FontWeight.BOLD),
                                ft.Text(etiqueta, size=9, color=color),
                            ], spacing=1, expand=True),
                            ft.Text(f"${float(linea.total_usd):.2f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=6,
                    )
                )
            
            contenido.controls.append(ft.Divider(height=5))
        
        # Total seleccionado
        texto_total_sel = ft.Text("Seleccionado: $0.00", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY)
        
        def _cobrar_seleccionados(_):
            lineas_seleccionadas = []
            total_sel = 0.0
            primera_estadia = None
            
            for hid, checks in checkboxes_por_hab.items():
                for lid, (cb, monto) in checks.items():
                    if cb.value:
                        lineas_seleccionadas.append(lid)
                        total_sel += monto
                        if not primera_estadia:
                            # Obtener la estadía de esta línea
                            sesion2 = SesionLocal()
                            try:
                                linea = sesion2.query(FolioLinea).filter(FolioLinea.id == lid).first()
                                if linea:
                                    primera_estadia = sesion2.query(Estadia).options(
                                        selectinload(Estadia.habitacion),
                                        selectinload(Estadia.ledger_movimientos),
                                        selectinload(Estadia.folio_lineas),
                                        selectinload(Estadia.huespedes),
                                    ).filter(Estadia.id == linea.estadia_id).first()
                            finally:
                                sesion2.close()
            
            if not lineas_seleccionadas:
                self.pagina.open(ft.SnackBar(content=ft.Text("Seleccione al menos un cargo")))
                return
            
            self.pagina.close(dlg_seleccion)
            
            dlg_pago = DialogoPago(
                self.pagina,
                primera_estadia,
                total_sel,
                al_completar=lambda: self._cargar_grupos(),
                lineas_ids=lineas_seleccionadas,
            )
            dlg_pago.mostrar()
        
        dlg_seleccion = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.SELECT_ALL, color=ft.Colors.PRIMARY),
                ft.Text(f"Cobrar Selección - {grupo.nombre}"),
            ]),
            content=ft.Container(
                content=ft.Column([
                    contenido,
                    ft.Divider(),
                    texto_total_sel,
                ], spacing=5),
                width=600,
                height=500,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg_seleccion)),
                ft.ElevatedButton(
                    "Cobrar Seleccionados",
                    icon=ft.Icons.PAYMENTS,
                    bgcolor=ft.Colors.GREEN_700,
                    color=ft.Colors.ON_PRIMARY,
                    on_click=_cobrar_seleccionados,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dlg_seleccion)
        
        # Calcular total inicial
        self._actualizar_total_seleccionado(checkboxes_por_hab, texto_total_sel)

    def _marcar_todos(self, checkboxes, valor):
        for cb, monto in checkboxes.values():
            cb.value = valor
        # Actualizar total
        self._actualizar_total_seleccionado_from_checks(checkboxes)

    def _actualizar_total_seleccionado(self, checkboxes_por_hab, texto_widget):
        total = 0.0
        for hid, checks in checkboxes_por_hab.items():
            for cb, monto in checks.values():
                if cb.value:
                    total += monto
        texto_widget.value = f"Seleccionado: ${total:.2f}"
        texto_widget.update()

    def _actualizar_total_seleccionado_from_checks(self, checkboxes):
        # Para los botones de marcar/desmarcar
        pass

    def _eliminar_grupo(self, grupo):
        def confirmar_eliminacion(e):
            sesion = SesionLocal()
            try:
                for hab in grupo.habitaciones:
                    hab.grupo_id = None
                
                sesion.delete(grupo)
                sesion.commit()
                self.pagina.open(ft.SnackBar(content=ft.Text(f"Grupo '{grupo.nombre}' eliminado")))
                self._cargar_grupos()
            except Exception as e:
                sesion.rollback()
                print(f"Error eliminando grupo: {e}")
            finally:
                sesion.close()
            self.pagina.close(dlg_confirm)
        
        dlg_confirm = ft.AlertDialog(
            title=ft.Text("Confirmar eliminación"),
            content=ft.Text(f"¿Está seguro de eliminar el grupo '{grupo.nombre}'? Las habitaciones no serán afectadas."),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(dlg_confirm)),
                ft.ElevatedButton("Eliminar", bgcolor=ft.Colors.ERROR, on_click=confirmar_eliminacion),
            ],
        )
        self.pagina.open(dlg_confirm)

    def construir(self):
        self._cargar_grupos()
        return self
