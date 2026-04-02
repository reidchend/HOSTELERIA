# modules/rooms/pantalla_grupos.py

import flet as ft
from database.connection import SesionLocal
from database.models import (
    GrupoHabitacion, 
    Habitacion, 
    Estadia, 
    Huesped,
    LedgerMovimiento,
    EstadoHabitacion,
)
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from modules.finance.payment_dialog import DialogoPago
from modules.rooms.checkin_grupal import DialogoCheckInGrupal


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
                    selectinload(GrupoHabitacion.estadias).selectinload(Estadia.ledger_movimientos),
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
                        ft.Icon(ft.Icons.GROUP_WORK_OUTLINED, size=64, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text("No hay grupos creados", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text("Seleccione habitaciones del dashboard y cree un grupo", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
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

    def _crear_tarjeta_grupo(self, grupo: GrupoHabitacion) -> ft.Container:
        habs_activas = [h for h in grupo.habitaciones if h.estado == EstadoHabitacion.OCCUPIED]
        
        total_deuda = 0
        for est in grupo.estadias:
            if est.activa:
                debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
                haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                total_deuda += debe - haber
        
        hab_numeros = ", ".join([h.numero for h in grupo.habitaciones])
        
        color_grupo = grupo.color_etiqueta or "#8B5CF6"
        
        nombre_principal = ""
        if grupo.huesped_principal:
            nombre_principal = f"{grupo.huesped_principal.nombre} {grupo.huesped_principal.apellido}"
        
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Container(width=8, height=40, bgcolor=color_grupo, border_radius=4),
                        ft.Column([
                            ft.Text(grupo.nombre, size=18, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Habitaciones: {hab_numeros}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ], spacing=2),
                    ], spacing=10),
                    margin=ft.margin.only(bottom=10),
                ),
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Total Deuda", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(f"${total_deuda:.2f}", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.ERROR),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=1,
                    ),
                    ft.VerticalDivider(),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Huésped Principal", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(nombre_principal or "No asignado", size=14),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=2,
                    ),
                    ft.VerticalDivider(),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Hab. Ocupadas", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(f"{len(habs_activas)}/{len(grupo.habitaciones)}", size=20, weight=ft.FontWeight.BOLD),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=1,
                    ),
                ], spacing=10),
                ft.Row([
                    ft.ElevatedButton(
                        "Ver Detalles",
                        icon=ft.Icons.VISIBILITY,
                        on_click=lambda e, g=grupo: self._ver_detalles(g),
                    ),
                    ft.ElevatedButton(
                        "Cobrar",
                        icon=ft.Icons.PAYMENT,
                        bgcolor=ft.Colors.PRIMARY,
                        on_click=lambda e, g=grupo: self._cobrar_grupo(g),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="Eliminar grupo",
                        on_click=lambda e, g=grupo: self._eliminar_grupo(g),
                    ),
                ], spacing=10),
            ], spacing=10),
            padding=20,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=12,
        )

    def _ver_detalles(self, grupo: GrupoHabitacion):
        contenido = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        
        contenido.controls.append(
            ft.Container(
                content=ft.Text("Habitaciones del Grupo", size=16, weight=ft.FontWeight.BOLD),
            )
        )
        
        for hab in grupo.habitaciones:
            estado_color = ft.Colors.GREEN_700 if hab.estado == EstadoHabitacion.FREE else ft.Colors.RED_700
            
            contenido.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(f"Hab. {hab.numero}", weight=ft.FontWeight.BOLD),
                        ft.Text(f"({hab.tipo})", color=ft.Colors.ON_SURFACE_VARIANT),
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
        
        contenido.controls.append(ft.Divider())
        contenido.controls.append(
            ft.Text("Estadías Activas", size=16, weight=ft.FontWeight.BOLD)
        )
        
        for est in grupo.estadias:
            if est.activa:
                debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
                haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                saldo = debe - haber
                
                huesped_nombres = ", ".join([h.nombre_completo for h in est.huespedes[:2]])
                
                contenido.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text(f"Habitación {est.habitacion.numero}", weight=ft.FontWeight.BOLD),
                            ft.Text(f"Huéspedes: {huesped_nombres}", size=12),
                            ft.Text(f"Entrada: {est.entrada.strftime('%Y-%m-%d %H:%M')}", size=12),
                            ft.Text(f"Saldo: ${saldo:.2f}", size=14, weight=ft.FontWeight.BOLD, 
                                   color=ft.Colors.ERROR if saldo > 0 else ft.Colors.GREEN_700),
                        ], spacing=5),
                        padding=10,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                    )
                )
        
        dlg = ft.AlertDialog(
            title=ft.Text(f"Detalles: {grupo.nombre}"),
            content=ft.Container(content=contenido, width=500, height=400),
            actions=[ft.TextButton("Cerrar", on_click=lambda _: self.pagina.close(dlg))],
        )
        self.pagina.open(dlg)

    def _cobrar_grupo(self, grupo: GrupoHabitacion):
        total_deuda = 0
        estadias_activas = []
        
        for est in grupo.estadias:
            if est.activa:
                debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
                haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                saldo = debe - haber
                if saldo > 0:
                    total_deuda += saldo
                    estadias_activas.append(est)
        
        if not estadias_activas:
            self.pagina.show_snack_bar(
                ft.SnackBar(content=ft.Text("No hay deuda pendiente en este grupo"))
            )
            return
        
        def al_pagar(monto_usd, monto_bs, metodo, referencia, tasa_cambio):
            sesion = SesionLocal()
            try:
                for est in estadias_activas:
                    debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
                    haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                    saldo = debe - haber
                    
                    if saldo <= 0:
                        continue
                    
                    monto_pagar = min(saldo, float(monto_usd))
                    
                    from database.models import LedgerMovimiento, TipoMovimiento
                    mov = LedgerMovimiento(
                        estadia_id=est.id,
                        tipo=TipoMovimiento.PAGO,
                        concepto=f"Pago grupal - {grupo.nombre}",
                        debe_usd=0,
                        haber_usd=monto_pagar,
                        tasa_cambio=tasa_cambio,
                        referencia=referencia,
                    )
                    sesion.add(mov)
                
                sesion.commit()
                self.pagina.show_snack_bar(
                    ft.SnackBar(content=ft.Text(f"Pago de ${total_deuda:.2f} registrado para {grupo.nombre}"))
                )
                self._cargar_grupos()
            except Exception as e:
                sesion.rollback()
                print(f"Error en pago grupal: {e}")
            finally:
                sesion.close()
        
        dlg_pago = DialogoPago(
            self.pagina,
            monto_esperado=total_deuda,
            al_confirmar_pago=al_pagar,
        )
        dlg_pago.mostrar()

    def _eliminar_grupo(self, grupo: GrupoHabitacion):
        def confirmar_eliminacion(e):
            sesion = SesionLocal()
            try:
                for hab in grupo.habitaciones:
                    hab.grupo_id = None
                
                sesion.delete(grupo)
                sesion.commit()
                self.pagina.show_snack_bar(
                    ft.SnackBar(content=ft.Text(f"Grupo '{grupo.nombre}' eliminado"))
                )
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