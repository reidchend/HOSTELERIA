# modules/rooms/checkin.py

import flet as ft
from datetime import datetime, timedelta
from database.connection import SesionLocal
from utils.calculos_financieros import leer_config_financiera
from database.models import (
    Habitacion,
    EstadoHabitacion,
    Huesped,
    Estadia,
    BitacoraEvento,
)
from modules.finance.engine import folio as folio_engine
from modules.finance.bitacora import registrar as _bita
from database.models import TipoEvento
from modules.finance.payment_dialog import DialogoPago


class DialogoCheckIn:
    """
    Formulario de check-in para una habitación libre.
    Permite registrar al huésped titular y sus acompañantes,
    calcular el total de la estadía y lanzar el módulo de cobro.

    Bitácora / Telegram:
      · Si omite el pago  → "Hab# $XX.XX pendiente por cancelar"
      · Si cobra ahora    → el mensaje lo registra payment_dialog al finalizar

    Soporta dos modos de visualización:
      · Modal (tradicional): mostrar()
      · Ventana flotante: mostrar_como_ventana()
    """

    def __init__(self, pagina: ft.Page, habitacion: Habitacion, al_completar):
        self.pagina = pagina
        self.habitacion = habitacion
        self.al_completar = al_completar
        self.dialogo = None
        self.ventana_flotante = None

        self.controles_acompanantes = []
        self.estadia_actual = None
        self.total_calculado = 0.0
        self._hab_numero = habitacion.numero  # para el mensaje

        # ── Campos de fecha ─────────────────────────────────────────────────
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        fecha_sal = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"[CheckIn] INIT: hoy={fecha_hoy}, salida={fecha_sal}")

        self.campo_entrada = ft.TextField(
            label="Entrada",
            value=fecha_hoy,
            read_only=True,
            expand=1,
            prefix_icon=ft.Icons.LOGIN,
        )
        manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.campo_salida = ft.TextField(
            label="Salida Estimada",
            value=manana,
            expand=1,
            prefix_icon=ft.Icons.LOGOUT,
            on_submit=lambda _: self.campo_documento.focus(),
        )

        # ── Campos del huésped titular ──────────────────────────────────────
        self.campo_documento = ft.TextField(
            label="Documento Titular",
            prefix_icon=ft.Icons.BADGE,
            helper_text="Escriba y pulse Enter para buscar",
            on_submit=self.evento_buscar_huesped,
        )
        self.campo_nombre = ft.TextField(label="Nombres", expand=1)
        self.campo_apellido = ft.TextField(label="Apellidos", expand=1)
        self.campo_fecha_nac = ft.TextField(
            label="F. Nacimiento", hint_text="YYYY-MM-DD", expand=1
        )
        self.campo_nacionalidad = ft.TextField(
            label="Nacionalidad", value="Venezolano/a", expand=1
        )
        self.campo_profesion = ft.TextField(label="Profesión", expand=1)
        self.campo_telefono = ft.TextField(label="Teléfono", expand=1)
        self.campo_vehiculo = ft.TextField(
            label="Vehículo (Placa/Marca)", prefix_icon=ft.Icons.DIRECTIONS_CAR
        )

        # ── Sección de acompañantes ─────────────────────────────────────────
        self.contenedor_acompanantes = ft.Column(spacing=10)
        self.btn_agregar_acompanante = ft.TextButton(
            "Añadir Acompañante",
            icon=ft.Icons.ADD_REACTION,
            on_click=self.agregar_campo_acompanante,
        )

        self.btn_guardar = ft.ElevatedButton(
            "Registrar Estadía",
            icon=ft.Icons.SAVE,
            style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_800),
            on_click=self.guardar_checkin,
            height=50,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # BÚSQUEDA DE HUÉSPEDES
    # ─────────────────────────────────────────────────────────────────────────

    def evento_buscar_huesped(self, evento):
        self.buscar_huesped(evento)

    def buscar_huesped(self, evento):
        if not self.campo_documento.value:
            return
        sesion = SesionLocal()
        huesped = (
            sesion.query(Huesped)
            .filter(Huesped.documento == self.campo_documento.value)
            .first()
        )
        if huesped:
            self.campo_nombre.value = huesped.nombre
            self.campo_apellido.value = huesped.apellido
            self.campo_fecha_nac.value = (
                huesped.fecha_nacimiento.strftime("%Y-%m-%d")
                if huesped.fecha_nacimiento
                else ""
            )
            self.campo_nacionalidad.value = huesped.nacionalidad
            self.campo_profesion.value = huesped.profesion
            self.campo_telefono.value = huesped.telefono
            self.campo_vehiculo.value = huesped.vehiculo

            if huesped.lista_negra:
                motivo = huesped.motivo_veto or "Sin motivo especificado."
                contenido_original = self.dialogo.content
                acciones_originales = self.dialogo.actions

                def _continuar(_):
                    self.dialogo.content = contenido_original
                    self.dialogo.actions = acciones_originales
                    self.dialogo.update()

                def _cancelar(_):
                    self.pagina.close(self.dialogo)

                self.dialogo.content = ft.Container(
                    width=500,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.BLOCK, color=ft.Colors.RED_700, size=28
                                    ),
                                    ft.Column(
                                        [
                                            ft.Text(
                                                "HUÉSPED EN LISTA NEGRA",
                                                color=ft.Colors.RED_700,
                                                weight="bold",
                                                size=15,
                                            ),
                                            ft.Text(
                                                huesped.nombre_completo,
                                                size=13,
                                                color=ft.Colors.GREY_800,
                                            ),
                                        ],
                                        spacing=2,
                                    ),
                                ],
                                spacing=10,
                            ),
                            ft.Container(
                                content=ft.Column(
                                    [
                                        ft.Text(
                                            "Motivo del veto:",
                                            size=11,
                                            color=ft.Colors.GREY_600,
                                        ),
                                        ft.Text(
                                            motivo,
                                            size=13,
                                            color=ft.Colors.RED_800,
                                            weight="bold",
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                bgcolor=ft.Colors.RED_50,
                                padding=12,
                                border_radius=8,
                                border=ft.border.all(1, ft.Colors.RED_200),
                            ),
                            ft.Text(
                                "Puedes continuar el check-in bajo tu responsabilidad "
                                "o cancelar la operación.",
                                size=11,
                                color=ft.Colors.GREY_600,
                                italic=True,
                            ),
                        ],
                        spacing=12,
                        tight=True,
                    ),
                )
                self.dialogo.actions = [
                    ft.TextButton(
                        "✕ Cancelar check-in",
                        style=ft.ButtonStyle(color=ft.Colors.RED_700),
                        on_click=_cancelar,
                    ),
                    ft.ElevatedButton(
                        "Continuar de todas formas →",
                        bgcolor=ft.Colors.ORANGE_700,
                        color="white",
                        on_click=_continuar,
                    ),
                ]
                self.dialogo.update()

            elif float(huesped.credito_usd or 0) < -0.01:
                deuda = abs(float(huesped.credito_usd))
                self.pagina.open(
                    ft.SnackBar(
                        ft.Text(
                            f"⚠ {huesped.nombre} tiene una deuda de ${deuda:.2f} "
                            "de estadías anteriores. Se cargará automáticamente.",
                            color=ft.Colors.WHITE,
                        ),
                        bgcolor=ft.Colors.ORANGE_800,
                        duration=6000,
                    )
                )
            else:
                self.pagina.open(
                    ft.SnackBar(
                        ft.Text(f"Huésped {huesped.nombre} cargado"), bgcolor="green"
                    )
                )
        sesion.close()
        self.pagina.update()

    # ─────────────────────────────────────────────────────────────────────────
    # ACOMPAÑANTES
    # ─────────────────────────────────────────────────────────────────────────

    def agregar_campo_acompanante(self, evento):
        if len(self.controles_acompanantes) >= (self.habitacion.capacidad_maxima - 1):
            self.pagina.open(
                ft.SnackBar(
                    ft.Text("Capacidad máxima de huéspedes alcanzada"), bgcolor="orange"
                )
            )
            return
        campo_doc = ft.TextField(
            label="Doc. Acompañante",
            expand=2,
            on_submit=self.buscar_acompanante_dinamico,
        )
        campo_nombre = ft.TextField(label="Nombre", expand=3)
        campo_apellido = ft.TextField(label="Apellido", expand=3)
        fila = ft.Row(
            [
                campo_doc,
                campo_nombre,
                campo_apellido,
                ft.IconButton(
                    ft.Icons.DELETE_OUTLINE,
                    icon_color="red",
                    on_click=lambda _, f=None: None,
                ),
            ]
        )
        fila.controls[-1].on_click = lambda _, f=fila: self.eliminar_acompanante(f)
        self.controles_acompanantes.append(fila)
        self.contenedor_acompanantes.controls.append(fila)
        self.pagina.update()
        campo_doc.focus()

    def eliminar_acompanante(self, fila):
        if fila in self.controles_acompanantes:
            self.controles_acompanantes.remove(fila)
        if fila in self.contenedor_acompanantes.controls:
            self.contenedor_acompanantes.controls.remove(fila)
        self.pagina.update()

    def buscar_acompanante_dinamico(self, evento):
        doc = evento.control.value
        if not doc:
            return
        sesion = SesionLocal()
        huesped = sesion.query(Huesped).filter(Huesped.documento == doc).first()
        if huesped:
            controles_fila = evento.control.parent.controls
            controles_fila[1].value = huesped.nombre
            controles_fila[2].value = huesped.apellido
        sesion.close()
        self.pagina.update()

    # ─────────────────────────────────────────────────────────────────────────
    # GUARDADO DEL CHECK-IN
    # ─────────────────────────────────────────────────────────────────────────

    def guardar_checkin(self, evento):
        if not self.campo_documento.value or not self.campo_nombre.value:
            self.pagina.open(
                ft.SnackBar(ft.Text("Faltan datos del titular"), bgcolor="red")
            )
            return

        sesion = SesionLocal()
        try:
            titular = self.obtener_o_crear_huesped(
                sesion,
                self.campo_documento.value,
                self.campo_nombre.value,
                self.campo_apellido.value,
                es_titular=True,
            )
            lista_huespedes = [titular]

            for fila in self.controles_acompanantes:
                doc = fila.controls[0].value
                nombre = fila.controls[1].value
                apell = fila.controls[2].value
                if doc and nombre:
                    acomp = self.obtener_o_crear_huesped(
                        sesion, doc, nombre, apell, es_titular=False
                    )
                    lista_huespedes.append(acomp)

            habitacion_bd = (
                sesion.query(Habitacion)
                .filter(Habitacion.id == self.habitacion.id)
                .first()
            )
            habitacion_bd.estado = EstadoHabitacion.OCCUPIED

            fecha_entrada = datetime.strptime(self.campo_entrada.value, "%Y-%m-%d")
            fecha_salida = datetime.strptime(self.campo_salida.value, "%Y-%m-%d")
            print(
                f"[CheckIn] DEBUG: entrada={self.campo_entrada.value}, salida={self.campo_salida.value}"
            )
            noches = max(1, (fecha_salida - fecha_entrada).days)
            precio_noche = (
                habitacion_bd.precio_actual_usd or habitacion_bd.precio_base_usd
            )

            self.estadia_actual = Estadia(
                habitacion_id=habitacion_bd.id,
                entrada=fecha_entrada,
                salida=fecha_salida,
                activa=True,
            )
            self.estadia_actual.huespedes = lista_huespedes
            sesion.add(self.estadia_actual)
            sesion.flush()

            config = leer_config_financiera(sesion)
            linea_hosp = folio_engine.crear_linea_hospedaje(
                sesion,
                estadia_id=self.estadia_actual.id,
                habitacion_numero=habitacion_bd.numero,
                noches=noches,
                precio_noche_usd=precio_noche,
                config=config,
                concepto_extra=(
                    f"Hospedaje — Hab. {habitacion_bd.numero} "
                    f"({noches} noche{'s' if noches > 1 else ''}) "
                    f"del {fecha_entrada.strftime('%d/%m/%Y')} "
                    f"al {fecha_salida.strftime('%d/%m/%Y')}"
                ),
            )
            monto_total = float(linea_hosp.total_usd)

            from decimal import Decimal

            titular_bd_fresco = sesion.get(Huesped, titular.id)
            credito = (
                Decimal(str(titular_bd_fresco.credito_usd or 0))
                if titular_bd_fresco
                else Decimal("0")
            )
            if titular_bd_fresco and credito < Decimal("-0.01"):
                deuda_anterior = abs(credito)
                folio_engine.crear_saldo_pendiente(
                    sesion,
                    estadia_id=self.estadia_actual.id,
                    monto_usd=deuda_anterior,
                    concepto="Deuda de estadías anteriores",
                    config=config,
                )
                titular_bd_fresco.credito_usd = Decimal("0")

            # ── Guardar datos para el mensaje posterior ──────────────────────
            self._hab_numero = habitacion_bd.numero
            self._monto_total = monto_total
            self._nombre_titular = titular.nombre_completo
            self._noches = noches
            self._fecha_salida = fecha_salida.strftime("%d/%m/%Y")
            self._estadia_id = self.estadia_actual.id
            self._bitacora_event_id = None  # Se guarda cuando se crea el evento

            sesion.commit()
            sesion.refresh(self.estadia_actual)
            self.total_calculado = monto_total
            self.pagina.close(self.dialogo)
            self.preguntar_por_pago()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(
                ft.SnackBar(ft.Text(f"Error en Check-In: {error}"), bgcolor="red")
            )
        finally:
            sesion.close()

    # ─────────────────────────────────────────────────────────────────────────
    # DECISIÓN DE PAGO
    # ─────────────────────────────────────────────────────────────────────────

    def preguntar_por_pago(self):
        def ir_a_cobrar(evento):
            self.pagina.close(dialogo_confirmacion)

            from database.connection import SesionLocal as _SL
            from database.models import FolioLinea as _FL

            _ses = _SL()
            try:
                _lineas = (
                    _ses.query(_FL)
                    .filter(
                        _FL.estadia_id == self.estadia_actual.id,
                        _FL.cancelada == False,
                    )
                    .all()
                )
                _ids = [l.id for l in _lineas]
                _total = sum(float(l.total_usd) for l in _lineas)
            finally:
                _ses.close()

            if self._bitacora_event_id is None:
                _ses2 = _SL()
                try:
                    _bita(
                        sesion=_ses2,
                        pagina=self.pagina,
                        tipo=TipoEvento.CHECKIN,
                        habitacion=self._hab_numero,
                        concepto=(
                            f"Hab{self._hab_numero} ${self._monto_total:.2f} "
                            f"pendiente por cancelar"
                        ),
                        monto_usd=self._monto_total,
                        confirmado=False,
                        notificar_telegram=False,
                    )
                    _ses2.commit()
                    self._bitacora_event_id = (
                        _ses2.query(BitacoraEvento)
                        .filter(BitacoraEvento.tipo == TipoEvento.CHECKIN)
                        .order_by(BitacoraEvento.id.desc())
                        .first()
                    ).id
                except Exception as e:
                    _ses2.rollback()
                    print(f"[CheckIn] Error creando bitácora: {e}")
                finally:
                    _ses2.close()

            modulo_pago = DialogoPago(
                self.pagina,
                self.estadia_actual,
                _total or self.total_calculado,
                al_completar=self.al_completar,
                lineas_ids=_ids,
                checkin_info={
                    "habitacion": self._hab_numero,
                    "monto": self._monto_total,
                    "nombre": self._nombre_titular,
                    "noches": self._noches,
                    "fecha_salida": self._fecha_salida,
                    "bitacora_event_id": self._bitacora_event_id,
                },
            )
            modulo_pago.mostrar()

        def omitir_pago(evento):
            self.pagina.close(dialogo_confirmacion)

            # Registrar bitácora con estado "pendiente por cancelar"
            sesion = SesionLocal()
            bitacora_id = None
            try:
                resultado = _bita(
                    sesion=sesion,
                    pagina=self.pagina,
                    tipo=TipoEvento.CHECKIN,
                    habitacion=self._hab_numero,
                    concepto=(
                        f"Hab{self._hab_numero} ${self._monto_total:.2f} "
                        f"pendiente por cancelar"
                    ),
                    monto_usd=self._monto_total,
                    confirmado=False,
                    notificar_telegram=False,
                    retornar_evento=True,
                )
                if resultado and isinstance(resultado, BitacoraEvento):
                    bitacora_id = resultado.id
                sesion.commit()
            except Exception as e:
                sesion.rollback()
                print(f"[CheckIn] Error al registrar bitácora omitir: {e}")
            finally:
                sesion.close()

            # Guardar event_id para uso posterior
            self._bitacora_event_id = bitacora_id

            # Telegram — mensaje de check-in pendiente (síncrono para obtener message_id)
            try:
                from modules.notifications.formatter import checkin_mensaje
                from modules.notifications import telegram as tg

                recep = (self.pagina.session.get("usuario_activo") or {}).get(
                    "nombre_completo", ""
                )
                msg = checkin_mensaje(
                    habitacion=self._hab_numero,
                    precio_usd=self._monto_total,
                    nombre=self._nombre_titular,
                    noches=self._noches,
                    fecha_salida=self._fecha_salida,
                    recepcionista=recep,
                    pagos=[],
                    pendiente=True,
                )
                exito, msg_id = tg.enviar_mensaje(msg)
                if exito and msg_id and bitacora_id:
                    from modules.notifications.dispatcher import (
                        guardar_telegram_message_id,
                    )

                    guardar_telegram_message_id(bitacora_id, str(msg_id))
            except Exception as e:
                print(f"[CheckIn] Error Telegram omitir: {e}")

            if self.al_completar:
                self.al_completar()

        dialogo_confirmacion = ft.AlertDialog(
            modal=True,
            title=ft.Text("Estadía Registrada"),
            content=ft.Text(
                f"Total estimado Hab. {self._hab_numero}: "
                f"$ {self.total_calculado:.2f}\n¿Desea registrar el pago ahora?"
            ),
            actions=[
                ft.TextButton("Omitir", on_click=omitir_pago),
                ft.ElevatedButton(
                    "Cobrar",
                    bgcolor=ft.Colors.GREEN_700,
                    color="white",
                    on_click=ir_a_cobrar,
                ),
            ],
        )
        self.pagina.open(dialogo_confirmacion)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def obtener_o_crear_huesped(
        self, sesion, documento, nombre, apellido, es_titular: bool
    ) -> Huesped:
        huesped = sesion.query(Huesped).filter(Huesped.documento == documento).first()
        if not huesped:
            huesped = Huesped(documento=documento, nombre=nombre, apellido=apellido)
            sesion.add(huesped)
        else:
            huesped.nombre = nombre
            huesped.apellido = apellido

        if es_titular:
            try:
                if self.campo_fecha_nac.value:
                    huesped.fecha_nacimiento = datetime.strptime(
                        self.campo_fecha_nac.value, "%Y-%m-%d"
                    ).date()
            except ValueError:
                pass
            huesped.nacionalidad = self.campo_nacionalidad.value
            huesped.profesion = self.campo_profesion.value
            huesped.telefono = self.campo_telefono.value
            huesped.vehiculo = self.campo_vehiculo.value

        sesion.flush()
        return huesped

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DEL DIÁLOGO
    # ─────────────────────────────────────────────────────────────────────────

    def construir(self) -> ft.AlertDialog:
        return ft.AlertDialog(
            title=ft.Text(f"Check-In — Habitación {self.habitacion.numero}"),
            content=ft.Container(
                width=700,
                content=ft.Column(
                    [
                        ft.Row([self.campo_entrada, self.campo_salida]),
                        ft.Divider(),
                        ft.Text("Datos del Titular", weight="bold", color="blue"),
                        self.campo_documento,
                        ft.Row([self.campo_nombre, self.campo_apellido]),
                        ft.Row([self.campo_fecha_nac, self.campo_nacionalidad]),
                        ft.Row([self.campo_profesion, self.campo_telefono]),
                        self.campo_vehiculo,
                        ft.Divider(),
                        ft.Row(
                            [
                                ft.Text("Acompañantes", weight="bold", color="blue"),
                                self.btn_agregar_acompanante,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        self.contenedor_acompanantes,
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    tight=True,
                    spacing=15,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)
                ),
                self.btn_guardar,
            ],
        )

    def mostrar(self):
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)
