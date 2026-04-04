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
from sqlalchemy.orm import selectinload
from utils import handle_error
from modules.finance.bitacora import registrar as _bita
import random


_COLORES_GRUPO = [
    "#EF4444", "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6", 
    "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"
]


class DialogoCheckInGrupal:
    def __init__(self, pagina: ft.Page, habitaciones: list, grupo: GrupoHabitacion, al_completar, estadias=None, al_refrescar=None):
        self.pagina = pagina
        self.habitaciones = habitaciones
        self.grupo = grupo
        self.al_completar = al_completar
        self.al_refrescar = al_refrescar
        self.estadias = estadias or []  # Para pasar las estadísticas al módulo de pagos
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
            self.pagina.open(ft.SnackBar(content=ft.Text("Documento y nombre son obligatorios")))
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
        
        if not contenido_tabs:
            contenido_tabs.append(
                ft.Container(
                    content=ft.Text("No hay habitaciones disponibles para check-in."),
                    padding=20,
                )
            )
        
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
        
        sesion = SesionLocal()
        try:
            for hab in self.habitaciones:
                reg = self.registros_habitacion.get(hab.id)
                if not reg or not reg["huespedes"]:
                    continue
                
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
                precio_noche_decimal = hab.precio_actual_usd or 0
                precio_noche = float(precio_noche_decimal)
                
                print(f"[DEBUG CheckInGrupal] Hab {hab.numero}: precio_noche_decimal={precio_noche_decimal}, tipo={type(precio_noche_decimal)}, precio_noche_float={precio_noche}, noches={noches}")
                print(f"[DEBUG CheckInGrupal] precio_noche * noches = {precio_noche * noches}")
                
                datos_grupo.append({
                    "numero": hab.numero,
                    "huesped": huesped_nombre,
                    "total_sin_iva": round(precio_noche * noches, 2),
                })
                
                if precio_noche > 0:
                    # Usar la función del engine de folio para calcular IVA correctamente
                    from modules.finance.engine import folio as folio_engine
                    from utils.calculos_financieros import leer_config_financiera
                    from decimal import Decimal
                    
                    config = leer_config_financiera(sesion)
                    linea_hosp = folio_engine.crear_linea_hospedaje(
                        sesion=sesion,
                        estadia_id=estadia.id,
                        habitacion_numero=hab.numero,
                        noches=noches,
                        precio_noche_usd=Decimal(str(hab.precio_actual_usd or 0)),
                        config=config,
                        concepto_extra=f"Hospedaje {hab.numero} - {noches} noche(s)",
                        aplica_iva=True,
                    )
                    
                    linea_hosp = folio_engine.crear_linea_hospedaje(
                        sesion=sesion,
                        estadia_id=estadia.id,
                        habitacion_numero=hab.numero,
                        noches=noches,
                        precio_noche_usd=precio_noche,
                        config=config,
                        concepto_extra=f"Hospedaje {hab.numero} - {noches} noche(s)",
                        aplica_iva=True,  # Aplicar IVA normalmente
                    )
                
                # Registrar en bitácora SIN enviar mensaje individual a Telegram
                evento_bitacora = _bita(
                    sesion=sesion,
                    pagina=self.pagina,
                    tipo=TipoEvento.CHECKIN,
                    concepto=f"CHECK-IN GRUPO '{self.grupo.nombre}' - Hab. {hab.numero}",
                    habitacion=f"{hab.numero} (Grupo: {self.grupo.nombre})",
                    monto_usd=precio_noche * noches,
                    recepcionista="Recepcionista",
                    confirmado=True,
                    notificar_telegram=False,
                )
                sesion.flush()
                
                # Re-vincular la habitación a la sesión actual para persistir el cambio de estado
                hab_actual = sesion.get(Habitacion, hab.id)
                if hab_actual:
                    hab_actual.estado = EstadoHabitacion.OCCUPIED
            
            # Commit final después de procesar todas las habitaciones
            sesion.commit()
        except Exception as e:
            sesion.rollback()
            handle_error(e, self.pagina, "Check-in grupal")
        finally:
            sesion.close()
        
        # Refrescar vistas de UI si se proporcionó callback
        if self.al_refrescar:
            try:
                self.al_refrescar()
            except Exception:
                pass
        
        # Calcular el total real del grupo (incluyendo IVA)
        sesion_total = SesionLocal()
        try:
            from sqlalchemy import func
            total_result = sesion_total.query(func.sum(FolioLinea.total_usd)).join(Estadia).filter(
                Estadia.grupo_id == self.grupo.id,
                FolioLinea.tipo == TipoLinea.HOSPEDAJE,
                FolioLinea.cancelada == False
            ).scalar()
            total_grupo = float(total_result or 0)
        finally:
            sesion_total.close()
        
        # Guardar los datos del grupo para usarlos después
        self._datos_telegram = {
            "nombre_grupo": self.grupo.nombre,
            "habitaciones": datos_grupo,
            "huesped_principal": datos_grupo[0]["huesped"] if datos_grupo else "",
            "total_grupo": total_grupo,
            "noches": (datetime.strptime(self.campo_salida.value, "%Y-%m-%d").date() - 
                       datetime.strptime(self.campo_entrada.value, "%Y-%m-%d").date()).days,
            "fecha_salida": datetime.strptime(self.campo_salida.value, "%Y-%m-%d").strftime("%d/%m/%Y"),
            "recepcionista": "Recepcionista",
        }
        
        # Guardar IDs de bitácora de cada estadía para el reply_to de Telegram
        self._bitacora_event_ids = []
        sesion_bitacora = SesionLocal()
        try:
            for hab in self.habitaciones:
                reg = self.registros_habitacion.get(hab.id)
                if not reg or not reg["huespedes"]:
                    continue
                precio_noche = float(hab.precio_actual_usd or 0)
                noches = (datetime.strptime(self.campo_salida.value, "%Y-%m-%d").date() - 
                          datetime.strptime(self.campo_entrada.value, "%Y-%m-%d").date()).days
                total_hosp = precio_noche * noches
                
                evento = _bita(
                    sesion=sesion_bitacora,
                    pagina=self.pagina,
                    tipo=TipoEvento.CHECKIN,
                    concepto=f"CHECK-IN GRUPO '{self.grupo.nombre}' - Hab. {hab.numero}",
                    habitacion=f"{hab.numero} (Grupo: {self.grupo.nombre})",
                    monto_usd=total_hosp,
                    recepcionista="Recepcionista",
                    confirmado=True,
                    notificar_telegram=False,  # Se envía solo el grupal
                    retornar_evento=True,
                )
                if evento:
                    self._bitacora_event_ids.append(evento.id)
            sesion_bitacora.commit()
        except Exception as e:
            sesion_bitacora.rollback()
            print(f"[CheckInGrupal] Error registrando bitácora: {e}")
        finally:
            sesion_bitacora.close()
        
        # Mostrar diálogo para preguntar si desea pagar o no
        self._mostrar_dialogo_pago(datos_grupo, total_grupo)

    def _mostrar_dialogo_pago(self, datos_grupo, total_grupo):
        def _(e):
            self.pagina.close(dialogo_confirmacion)
            if e.control.text == "Sí, proceder al pago":
                # Abrir módulo de pagos grupal
                self._abrir_pago_grupal(datos_grupo, total_grupo)
            elif e.control.text == "Omitir":
                # Registrar bitácora pendiente y enviar mensaje Telegram con reply_to
                self._omitir_pago_grupal()
        
        dialogo_confirmacion = ft.AlertDialog(
            title=ft.Text("Check-in Grupal Completado"),
            content=ft.Text(f"El grupo '{self.grupo.nombre}' ha sido registrado.\n\nTotal a pagar: ${total_grupo:.2f}\n\n¿Desea proceder al pago ahora?"),
            actions=[
                ft.TextButton("Omitir", on_click=_),
                ft.ElevatedButton("Sí, proceder al pago", on_click=_),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.pagina.open(dialogo_confirmacion)

    def _omitir_pago_grupal(self):
        """Registra cuenta pendiente y envía mensaje a Telegram guardando el message_id."""
        if not hasattr(self, '_datos_telegram'):
            return
        
        datos = self._datos_telegram
        
        # Registrar evento de bitácora pendiente
        sesion = SesionLocal()
        bitacora_id = None
        try:
            evento = _bita(
                sesion=sesion,
                pagina=self.pagina,
                tipo=TipoEvento.CHECKIN,
                concepto=f"CHECK-IN GRUPO '{datos['nombre_grupo']}' ${datos['total_grupo']:.2f} pendiente por cancelar",
                habitacion=f"Grupo {datos['nombre_grupo']}",
                monto_usd=datos["total_grupo"],
                confirmado=False,
                notificar_telegram=False,
                retornar_evento=True,
            )
            if evento:
                bitacora_id = evento.id
            sesion.commit()
        except Exception as e:
            sesion.rollback()
            print(f"[CheckInGrupal] Error bitácora omitir: {e}")
        finally:
            sesion.close()
        
        # Enviar mensaje de Telegram SÍNCRONAMENTE para obtener message_id
        try:
            from modules.notifications.formatter import checkin_grupal_mensaje
            from modules.notifications import telegram as tg
            from modules.notifications.dispatcher import guardar_telegram_message_id
            
            msg = checkin_grupal_mensaje(
                nombre_grupo=datos["nombre_grupo"],
                habitaciones=datos["habitaciones"],
                huesped_principal=datos["huesped_principal"],
                total_grupo=datos["total_grupo"],
                noches=datos["noches"],
                fecha_salida=datos["fecha_salida"],
                recepcionista=datos["recepcionista"],
                pendiente=True,
                pagos=[],
            )
            exito, msg_id = tg.enviar_mensaje(msg)
            if exito and msg_id and bitacora_id:
                guardar_telegram_message_id(bitacora_id, str(msg_id))
        except Exception as e:
            print(f"[CheckInGrupal] Error Telegram omitir: {e}")
        
        self.pagina.open(ft.SnackBar(content=ft.Text(f"Check-in grupal completado para {datos['nombre_grupo']} (pendiente por cancelar)")))
        if self.al_completar:
            self.al_completar()

    def _enviar_mensaje_telegram(self, pendiente=False, pagos=None):
        """Envía el mensaje de check-in grupal a Telegram."""
        if not hasattr(self, '_datos_telegram'):
            return
        
        try:
            from modules.notifications.dispatcher import enviar_checkin_grupal
            
            datos = self._datos_telegram
            enviar_checkin_grupal(
                nombre_grupo=datos["nombre_grupo"],
                habitaciones=datos["habitaciones"],
                huesped_principal=datos["huesped_principal"],
                total_grupo=datos["total_grupo"],
                noches=datos["noches"],
                fecha_salida=datos["fecha_salida"],
                recepcionista=datos["recepcionista"],
                pendiente=pendiente,
                pagos=pagos,
            )
        except Exception as e:
            print(f"[CheckInGrupal] Error enviando mensaje Telegram: {e}")

    def _abrir_pago_grupal(self, datos_grupo, total_grupo):
        from modules.finance.payment_dialog_grupal import DialogoPagoGrupal
        
        # Obtener las estadísticas creadas
        sesion = SesionLocal()
        estadias_grupo = []
        try:
            estadias_grupo = sesion.query(Estadia).options(
                selectinload(Estadia.habitacion),
                selectinload(Estadia.ledger_movimientos),
                selectinload(Estadia.folio_lineas),
            ).filter(
                Estadia.grupo_id == self.grupo.id,
                Estadia.activa == True
            ).all()
        finally:
            sesion.close()
        
        # Usar el DialogoPago regular con la primera estadía del grupo
        # El usuario puede pagar las demás después desde la pantalla de grupos o detallando cada habitación
        if estadias_grupo:
            from modules.finance.payment_dialog import DialogoPago
            
            primera_estadia = estadias_grupo[0]
            
            # Calcular el total del grupo para mostrar
            total_grupo_actual = sum(
                sum(float(m.debe_usd or 0) for m in est.ledger_movimientos) - 
                sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                for est in estadias_grupo
            )
            
            # Obtener lineas de folio para pagar
            lineas_ids = []
            for est in estadias_grupo:
                for linea in est.folio_lineas:
                    if not linea.cancelada:
                        lineas_ids.append(linea.id)
            
            modulo_pago = DialogoPago(
                self.pagina,
                primera_estadia,
                total_grupo_actual,
                al_completar=self.al_completar,
                lineas_ids=lineas_ids,
                checkin_info={
                    "habitacion": f"Grupo {self.grupo.nombre}",
                    "monto": total_grupo_actual,
                    "nombre": datos_grupo[0]["huesped"] if datos_grupo else "",
                    "noches": self._datos_telegram["noches"] if hasattr(self, '_datos_telegram') else 1,
                    "fecha_salida": self._datos_telegram["fecha_salida"] if hasattr(self, '_datos_telegram') else "",
                    "es_grupo": True,
                    "total_habitaciones": len(estadias_grupo),
                    "nombre_grupo": self.grupo.nombre,
                    "habitaciones_data": datos_grupo,
                },
            )
            modulo_pago.mostrar()

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
            self.pagina.open(ft.SnackBar(content=ft.Text("El nombre del grupo es obligatorio")))
            return
        
        sesion = SesionLocal()
        try:
            grupo = GrupoHabitacion(
                nombre=nombre,
                color_etiqueta=self._color_seleccionado,
            )
            sesion.add(grupo)
            sesion.flush()
            
            # Asignar el grupo_id a cada habitación
            for hab in self.habitaciones:
                hab.grupo_id = grupo.id
                sesion.add(hab)
                sesion.flush()
            
            sesion.commit()
            
            # Obtener el ID antes de cerrar la sesión
            grupo_id = grupo.id
            grupo_nombre = grupo.nombre
            
            self.pagina.close(self.dialogo)
            if self.al_crear:
                self.al_crear(grupo_id, grupo_nombre)
            
        except Exception as e:
            sesion.rollback()
            handle_error(e, self.pagina, "Crear grupo")
        finally:
            sesion.close()

    def mostrar(self):
        self.pagina.open(self.dialogo)
