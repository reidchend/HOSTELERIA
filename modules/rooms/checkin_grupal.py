# modules/rooms/checkin_grupal.py

import flet as ft
from datetime import datetime, timedelta
from database.connection import SesionLocal
from database.models import (
    Habitacion,
    EstadoHabitacion,
    Huesped,
    Estadia,
    GrupoHabitacion,
    TipoEstadia,
    FolioLinea,
    TipoLinea,
    LedgerMovimiento,
    TipoMovimiento,
    TipoEvento,
)
from utils import handle_error
from modules.finance.bitacora import registrar as _bita
import random


_COLORES_GRUPO = [
    "#EF4444", "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6", 
    "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"
]


class DialogoCheckInGrupal:
    def __init__(self, pagina: ft.Page, habitaciones: list, grupo: GrupoHabitacion, al_completar):
        self.pagina = pagina
        self.habitaciones = habitaciones
        self.grupo = grupo
        self.al_completar = al_completar
        self.dialogo = None
        
        self.registros_habitacion = {}
        
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        self.campo_entrada = ft.TextField(
            label="Entrada",
            value=fecha_hoy,
            read_only=True,
            expand=1,
            prefix_icon=ft.Icons.LOGIN,
        )
        self.campo_salida = ft.TextField(
            label="Salida Estimada",
            value=manana,
            expand=1,
            prefix_icon=ft.Icons.LOGOUT,
        )
        
        self._controles_tabs = {}
        self._construir_dialogo()

    def _crear_tabla_habitacion(self, hab: Habitacion) -> ft.Container:
        doc_field = ft.TextField(
            label="Documento",
            prefix_icon=ft.Icons.BADGE,
            width=140,
            on_submit=lambda e, h=hab: self._buscar_huesped(e, h),
        )
        nombre_field = ft.TextField(
            label="Nombre",
            prefix_icon=ft.Icons.PERSON,
            expand=1,
        )
        apellido_field = ft.TextField(
            label="Apellido",
            prefix_icon=ft.Icons.PERSON,
            expand=1,
        )
        telefono_field = ft.TextField(
            label="Teléfono",
            prefix_icon=ft.Icons.PHONE,
            width=120,
        )
        
        btn_agregar = ft.ElevatedButton(
            "Agregar",
            icon=ft.Icons.ADD,
            on_click=lambda e, h=hab: self._agregar_huesped_tabla(h),
        )
        
        tabla = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Doc", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Nombre", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Acompañante", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("", width=30)),
            ],
            rows=[],
        )
        
        self.registros_habitacion[hab.id] = {
            "doc": doc_field,
            "nombre": nombre_field,
            "apellido": apellido_field,
            "telefono": telefono_field,
            "tabla": tabla,
            "huespedes": [],
        }
        
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Text(f"Habitación {hab.numero}", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(f"({hab.tipo})", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ]),
                    margin=ft.margin.only(bottom=10),
                ),
                ft.Row([doc_field, nombre_field, apellido_field, telefono_field], spacing=10),
                ft.Row([btn_agregar], alignment=ft.MainAxisAlignment.END),
                ft.Divider(),
                ft.Text("Huéspedes registrados:", size=12, weight=ft.FontWeight.BOLD),
                tabla,
            ], spacing=5),
            padding=15,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=8,
            margin=ft.margin.only(bottom=10),
        )

    def _buscar_huesped(self, e, hab: Habitacion):
        doc = e.control.value.strip()
        if not doc:
            return
        sesion = SesionLocal()
        try:
            huesped = sesion.query(Huesped).filter(Huesped.documento == doc).first()
            if huesped:
                reg = self.registros_habitacion[hab.id]
                reg["doc"].value = huesped.documento
                reg["nombre"].value = huesped.nombre
                reg["apellido"].value = huesped.apellido
                reg["telefono"].value = huesped.telefono or ""
                self.dialogo.update()
        finally:
            sesion.close()

    def _agregar_huesped_tabla(self, hab: Habitacion):
        reg = self.registros_habitacion[hab.id]
        doc = reg["doc"].value.strip()
        nombre = reg["nombre"].value.strip()
        apellido = reg["apellido"].value.strip()
        
        if not doc or not nombre:
            self.pagina.show_snack_bar(
                ft.SnackBar(content=ft.Text("Documento y nombre son obligatorios"))
            )
            return
        
        huesped_data = {
            "documento": doc,
            "nombre": nombre,
            "apellido": apellido,
            "telefono": reg["telefono"].value.strip(),
            "es_titular": len(reg["huespedes"]) == 0,
        }
        
        reg["huespedes"].append(huesped_data)
        
        fila = ft.DataRow(cells=[
            ft.DataCell(ft.Text(doc)),
            ft.DataCell(ft.Text(f"{nombre} {apellido}")),
            ft.DataCell(ft.Text("Titular" if huesped_data["es_titular"] else "-")),
            ft.DataCell(
                ft.IconButton(
                    ft.Icons.DELETE,
                    icon_size=16,
                    on_click=lambda e, h=hab, idx=len(reg["huespedes"])-1: self._eliminar_huesped(h, idx),
                )
            ),
        ])
        reg["tabla"].rows.append(fila)
        
        reg["doc"].value = ""
        reg["nombre"].value = ""
        reg["apellido"].value = ""
        reg["telefono"].value = ""
        
        self.dialogo.update()

    def _eliminar_huesped(self, hab: Habitacion, idx: int):
        reg = self.registros_habitacion[hab.id]
        if idx < len(reg["huespedes"]):
            reg["huespedes"].pop(idx)
            if reg["tabla"].rows:
                reg["tabla"].rows.pop(idx)
            self.dialogo.update()

    def _construir_dialogo(self):
        contenido_tabs = []
        
        for hab in self.habitaciones:
            if hab.estado == EstadoHabitacion.FREE:
                contenido_tabs.append(self._crear_tabla_habitacion(hab))
        
        self._controles_tabs["contenido"] = ft.Column(contenido_tabs, scroll=ft.ScrollMode.AUTO)
        
        btn_checkin = ft.ElevatedButton(
            "Realizar Check-in Grupal",
            icon=ft.Icons.CHECK,
            bgcolor=ft.Colors.PRIMARY,
            color=ft.Colors.ON_PRIMARY,
            on_click=self._ejecutar_checkin,
        )
        
        btn_cancelar = ft.TextButton(
            "Cancelar",
            on_click=lambda _: self.pagina.close(self.dialogo),
        )
        
        self.dialogo = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.GROUP_WORK, color=ft.Colors.PRIMARY),
                ft.Text(f"Check-in Grupal: {self.grupo.nombre}"),
            ]),
            content=ft.Container(
                content=ft.Column([
                    ft.Row([self.campo_entrada, self.campo_salida], spacing=10),
                    ft.Divider(),
                    ft.Container(
                        content=self._controles_tabs["contenido"],
                        height=400,
                    ),
                ], spacing=10),
                width=700,
            ),
            actions=[btn_cancelar, btn_checkin],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _ejecutar_checkin(self, _):
        datos_grupo = []
        total_grupo = 0
        
        for hab in self.habitaciones:
            reg = self.registros_habitacion.get(hab.id)
            if not reg or not reg["huespedes"]:
                continue
            
            sesion = SesionLocal()
            try:
                huesped_titular = None
                huesped_nombre = ""
                for h_data in reg["huespedes"]:
                    huesped = sesion.query(Huesped).filter(
                        Huesped.documento == h_data["documento"]
                    ).first()
                    
                    if not huesped:
                        huesped = Huesped(
                            documento=h_data["documento"],
                            nombre=h_data["nombre"],
                            apellido=h_data["apellido"],
                            telefono=h_data.get("telefono", ""),
                        )
                        sesion.add(huesped)
                        sesion.flush()
                    
                    if h_data["es_titular"]:
                        huesped_titular = huesped
                        huesped_nombre = f"{huesped.nombre} {huesped.apellido}"
                
                if not huesped_titular:
                    continue
                
                fecha_ent = datetime.strptime(self.campo_entrada.value, "%Y-%m-%d")
                fecha_sal = datetime.strptime(self.campo_salida.value, "%Y-%m-%d")
                
                estadia = Estadia(
                    habitacion_id=hab.id,
                    entrada=fecha_ent,
                    salida=fecha_sal,
                    activa=True,
                    tipo=TipoEstadia.NOCHE,
                    notas=f"Grupo: {self.grupo.nombre}",
                    grupo_id=self.grupo.id,
                )
                sesion.add(estadia)
                sesion.flush()
                
                for h_data in reg["huespedes"]:
                    huesped = sesion.query(Huesped).filter(
                        Huesped.documento == h_data["documento"]
                    ).first()
                    if huesped:
                        estadia.huespedes.append(huesped)
                
                noches = (fecha_sal.date() - fecha_ent.date()).days
                precio_noche = float(hab.precio_actual_usd or 0)
                total_hospedaje = precio_noche * noches
                total_grupo += total_hospedaje
                
                datos_grupo.append({
                    "numero": hab.numero,
                    "huesped": huesped_nombre,
                    "total": total_hospedaje,
                })
                
                if precio_noche > 0:
                    folio_linea = FolioLinea(
                        estadia_id=estadia.id,
                        tipo=TipoLinea.HOSPEDAJE,
                        concepto=f"Hospedaje {hab.numero} - {noches} noche(s)",
                        cantidad=noches,
                        precio_unitario_usd=precio_noche,
                        aplica_iva=False,
                        subtotal_usd=precio_noche * noches,
                        iva_usd=0,
                        total_usd=precio_noche * noches,
                        cancelada=False,
                    )
                    sesion.add(folio_linea)
                    sesion.flush()
                    
                    ledger = LedgerMovimiento(
                        estadia_id=estadia.id,
                        tipo=TipoMovimiento.CARGO,
                        concepto=f"Hospedaje {hab.numero}",
                        debe_usd=precio_noche * noches,
                        haber_usd=0,
                        tasa_cambio=1,
                        folio_linea_id=folio_linea.id,
                    )
                    sesion.add(ledger)
                
                evento_bitacora = _bita(
                    sesion=sesion,
                    pagina=self.pagina,
                    tipo=TipoEvento.CHECKIN,
                    concepto=f"CHECK-IN GRUPO '{self.grupo.nombre}' - Hab. {hab.numero}",
                    habitacion=f"{hab.numero} (Grupo: {self.grupo.nombre})",
                    monto_usd=total_hospedaje,
                    recepcionista=getattr(getattr(self.pagina, 'session', {}), 'get', lambda k, d='': d)("usuario_activo", {}).get("nombre_completo", ""),
                    confirmado=True,
                    notificar_telegram=True,
                )
                sesion.flush()
                
                hab.estado = EstadoHabitacion.OCCUPIED
                
                sesion.commit()
                
            except Exception as e:
                sesion.rollback()
                handle_error(e, self.pagina, "Check-in grupal")
            finally:
                sesion.close()
        
        if datos_grupo:
            try:
                from modules.notifications.dispatcher import enviar_checkin_grupal
                
                huesped_principal = datos_grupo[0]["huesped"] if datos_grupo else ""
                noches = (datetime.strptime(self.campo_salida.value, "%Y-%m-%d").date() - 
                          datetime.strptime(self.campo_entrada.value, "%Y-%m-%d").date()).days
                fecha_salida_fmt = datetime.strptime(self.campo_salida.value, "%Y-%m-%d").strftime("%d/%m/%Y")
                recepcionista = getattr(getattr(self.pagina, 'session', {}), 'get', lambda k, d='': d)("usuario_activo", {}).get("nombre_completo", "")
                
                enviar_checkin_grupal(
                    nombre_grupo=self.grupo.nombre,
                    habitaciones=datos_grupo,
                    huesped_principal=huesped_principal,
                    total_grupo=total_grupo,
                    noches=noches,
                    fecha_salida=fecha_salida_fmt,
                    recepcionista=recepcionista,
                )
            except Exception as e:
                print(f"[CheckInGrupal] Error enviando mensaje Telegram: {e}")
        
        self.pagina.close(self.dialogo)
        if self.al_completar:
            self.al_completar()
        self.pagina.show_snack_bar(
            ft.SnackBar(content=ft.Text(f"Check-in grupal completado para {self.grupo.nombre}"))
        )

    def mostrar(self):
        self.pagina.open(self.dialogo)


class DialogoCrearGrupo:
    def __init__(self, pagina: ft.Page, habitaciones: list, al_crear):
        self.pagina = pagina
        self.habitaciones = habitaciones
        self.al_crear = al_crear
        self.dialogo = None
        
        self.campo_nombre = ft.TextField(
            label="Nombre del Grupo",
            prefix_icon=ft.Icons.GROUP_WORK,
            hint_text="Ej: Familia Pérez, Grupo Empresarial...",
        )
        
        self.seleccion_color = ft.SegmentedButton(
            segments=[
                ft.Segment(value=c, label=ft.Text("")) 
                for c in _COLORES_GRUPO
            ],
            selected=[],
            on_change=self._on_color_change,
        )
        
        self._color_seleccionado = _COLORES_GRUPO[0]
        self._construir_dialogo()

    def _on_color_change(self, e):
        if e.control.selected:
            self._color_seleccionado = e.control.selected[0]
            self.dialogo.update()

    def _construir_dialogo(self):
        preview_colores = ft.Row([
            ft.Container(
                content=ft.Text("●", color=c, size=24),
                on_click=lambda e, color=c: self._seleccionar_color(color),
            ) for c in _COLORES_GRUPO
        ], spacing=5)
        
        lista_habs = ", ".join([h.numero for h in self.habitaciones])
        
        self.dialogo = ft.AlertDialog(
            title=ft.Text("Crear Grupo de Habitaciones"),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"Habitaciones: {lista_habs}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    self.campo_nombre,
                    ft.Text("Color de identificación:", size=12, weight=ft.FontWeight.BOLD),
                    preview_colores,
                ], spacing=10),
                width=400,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                ft.ElevatedButton(
                    "Crear Grupo",
                    icon=ft.Icons.CHECK,
                    on_click=self._crear_grupo,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _seleccionar_color(self, color):
        self._color_seleccionado = color
        self.dialogo.update()

    def _crear_grupo(self, _):
        nombre = self.campo_nombre.value.strip()
        if not nombre:
            self.pagina.show_snack_bar(
                ft.SnackBar(content=ft.Text("El nombre del grupo es obligatorio"))
            )
            return
        
        sesion = SesionLocal()
        try:
            grupo = GrupoHabitacion(
                nombre=nombre,
                color_etiqueta=self._color_seleccionado,
            )
            sesion.add(grupo)
            sesion.flush()
            
            for hab in self.habitaciones:
                hab.grupo_id = grupo.id
            
            sesion.commit()
            
            self.pagina.close(self.dialogo)
            if self.al_crear:
                self.al_crear(grupo)
            
        except Exception as e:
            sesion.rollback()
            handle_error(e, self.pagina, "Crear grupo")
        finally:
            sesion.close()

    def mostrar(self):
        self.pagina.open(self.dialogo)