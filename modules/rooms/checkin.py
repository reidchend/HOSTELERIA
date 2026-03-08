# modules/rooms/checkin.py

import flet as ft
from datetime import datetime, timedelta
from database.connection import SesionLocal
from utils.calculos_financieros import leer_config_financiera
from database.models import LineaCuenta, TipoLinea, Habitacion, EstadoHabitacion, Huesped, Estadia
from modules.finance.payment_dialog import DialogoPago


class DialogoCheckIn:
    """
    Formulario de check-in para una habitación libre.
    Permite registrar al huésped titular y sus acompañantes,
    calcular el total de la estadía y lanzar el módulo de cobro.
    """

    def __init__(self, pagina: ft.Page, habitacion: Habitacion, al_completar):
        self.pagina        = pagina
        self.habitacion    = habitacion
        self.al_completar  = al_completar
        self.dialogo       = None

        self.controles_acompanantes  = []
        self.estadia_actual          = None
        self.total_calculado         = 0.0

        # ── Campos de fecha ─────────────────────────────────────────────────
        self.campo_entrada = ft.TextField(
            label="Entrada", value=datetime.now().strftime("%Y-%m-%d"),
            read_only=True, expand=1, prefix_icon=ft.Icons.LOGIN,
        )
        manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.campo_salida = ft.TextField(
            label="Salida Estimada", value=manana, expand=1,
            prefix_icon=ft.Icons.LOGOUT,
            on_submit=lambda _: self.campo_documento.focus(),
        )

        # ── Campos del huésped titular ──────────────────────────────────────
        self.campo_documento    = ft.TextField(
            label="Documento Titular", prefix_icon=ft.Icons.BADGE,
            helper_text="Escriba y pulse Enter para buscar",
            on_submit=self.evento_buscar_huesped,
        )
        self.campo_nombre       = ft.TextField(label="Nombres",       expand=1)
        self.campo_apellido     = ft.TextField(label="Apellidos",     expand=1)
        self.campo_fecha_nac    = ft.TextField(label="F. Nacimiento", hint_text="YYYY-MM-DD", expand=1)
        self.campo_nacionalidad = ft.TextField(label="Nacionalidad",  value="Venezolano/a", expand=1)
        self.campo_profesion    = ft.TextField(label="Profesión",     expand=1)
        self.campo_telefono     = ft.TextField(label="Teléfono",      expand=1)
        self.campo_vehiculo     = ft.TextField(
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
    # BÚSQUEDA DE HUÉSPEDES EXISTENTES
    # ─────────────────────────────────────────────────────────────────────────

    def evento_buscar_huesped(self, evento):
        """Busca el huésped al pulsar Enter en el campo de documento."""
        self.buscar_huesped(evento)
        self.campo_nombre.focus()

    def buscar_huesped(self, evento):
        """
        Rellena los campos del titular si el documento ya existe en la BD.
        Si el huésped está en lista negra, muestra una advertencia bloqueante.
        Si tiene deuda registrada (credito_usd negativo), informa al recepcionista.
        """
        if not self.campo_documento.value:
            return
        sesion = SesionLocal()
        huesped = sesion.query(Huesped).filter(
            Huesped.documento == self.campo_documento.value
        ).first()
        if huesped:
            self.campo_nombre.value       = huesped.nombre
            self.campo_apellido.value     = huesped.apellido
            self.campo_fecha_nac.value    = huesped.fecha_nacimiento.strftime("%Y-%m-%d") if huesped.fecha_nacimiento else ""
            self.campo_nacionalidad.value = huesped.nacionalidad
            self.campo_profesion.value    = huesped.profesion
            self.campo_telefono.value     = huesped.telefono
            self.campo_vehiculo.value     = huesped.vehiculo

            # ── Alerta de lista negra ──────────────────────────────────────
            if huesped.lista_negra:
                motivo = huesped.motivo_veto or "Sin motivo especificado."
                dlg_veto = ft.AlertDialog(
                    modal=True,
                    title=ft.Row([
                        ft.Icon(ft.Icons.BLOCK, color=ft.Colors.RED_700, size=22),
                        ft.Text("HUÉSPED EN LISTA NEGRA", color=ft.Colors.RED_700,
                                weight="bold"),
                    ], spacing=8),
                    content=ft.Container(
                        width=400,
                        content=ft.Column([
                            ft.Text(huesped.nombre_completo, size=15, weight="bold"),
                            ft.Text(f"Documento: {huesped.documento}", size=12,
                                    color=ft.Colors.GREY_600),
                            ft.Divider(),
                            ft.Container(
                                content=ft.Column([
                                    ft.Text("Motivo del veto:", size=11,
                                            color=ft.Colors.GREY_600),
                                    ft.Text(motivo, size=13, color=ft.Colors.RED_800,
                                            weight="bold"),
                                ], spacing=4),
                                bgcolor=ft.Colors.RED_50, padding=12,
                                border_radius=8,
                                border=ft.border.all(1, ft.Colors.RED_200),
                            ),
                            ft.Text(
                                "Puedes continuar el check-in bajo tu responsabilidad "
                                "o cancelar la operación.",
                                size=11, color=ft.Colors.GREY_600, italic=True,
                            ),
                        ], spacing=10, tight=True),
                    ),
                    actions=[
                        ft.TextButton(
                            "Cancelar check-in",
                            style=ft.ButtonStyle(color=ft.Colors.RED_700),
                            on_click=lambda _: (
                                self.pagina.close(dlg_veto),
                                self.pagina.close(self.dialogo),
                            ),
                        ),
                        ft.ElevatedButton(
                            "Continuar de todas formas",
                            bgcolor=ft.Colors.ORANGE_700, color="white",
                            on_click=lambda _: self.pagina.close(dlg_veto),
                        ),
                    ],
                    actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )
                self.pagina.open(dlg_veto)

            # ── Alerta de deuda pendiente ──────────────────────────────────
            elif (huesped.credito_usd or 0.0) < -0.01:
                deuda = abs(huesped.credito_usd)
                self.pagina.open(ft.SnackBar(
                    ft.Text(
                        f"⚠ {huesped.nombre} tiene una deuda de ${deuda:.2f} "
                        "de estadías anteriores. Se cargará automáticamente.",
                        color=ft.Colors.WHITE,
                    ),
                    bgcolor=ft.Colors.ORANGE_800,
                    duration=6000,
                ))
            else:
                self.pagina.open(ft.SnackBar(
                    ft.Text(f"Huésped {huesped.nombre} cargado"), bgcolor="green"
                ))
        sesion.close()
        self.pagina.update()

    # ─────────────────────────────────────────────────────────────────────────
    # ACOMPAÑANTES
    # ─────────────────────────────────────────────────────────────────────────

    def agregar_campo_acompanante(self, evento):
        """Agrega una fila de campos para un nuevo acompañante."""
        if len(self.controles_acompanantes) >= (self.habitacion.capacidad_maxima - 1):
            self.pagina.open(ft.SnackBar(
                ft.Text("Capacidad máxima de huéspedes alcanzada"), bgcolor="orange"
            ))
            return

        campo_doc     = ft.TextField(label="Doc. Acompañante", expand=2,
                                     on_submit=self.buscar_acompanante_dinamico)
        campo_nombre  = ft.TextField(label="Nombre",   expand=3)
        campo_apellido= ft.TextField(label="Apellido", expand=3)

        fila = ft.Row([
            campo_doc, campo_nombre, campo_apellido,
            ft.IconButton(
                ft.Icons.DELETE_OUTLINE, icon_color="red",
                on_click=lambda _, f=None: self.eliminar_acompanante(fila),
            ),
        ])
        # Corregir la referencia circular del botón de eliminar
        fila.controls[-1].on_click = lambda _, f=fila: self.eliminar_acompanante(f)

        self.controles_acompanantes.append(fila)
        self.contenedor_acompanantes.controls.append(fila)
        self.pagina.update()
        campo_doc.focus()

    def eliminar_acompanante(self, fila):
        """Elimina una fila de acompañante del formulario."""
        if fila in self.controles_acompanantes:
            self.controles_acompanantes.remove(fila)
        if fila in self.contenedor_acompanantes.controls:
            self.contenedor_acompanantes.controls.remove(fila)
        self.pagina.update()

    def buscar_acompanante_dinamico(self, evento):
        """Rellena nombre y apellido del acompañante si ya está registrado."""
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
        """
        Valida los datos, crea/actualiza la ficha del huésped y la estadía,
        cambia el estado de la habitación a OCUPADA y lanza el módulo de cobro.
        """
        if not self.campo_documento.value or not self.campo_nombre.value:
            self.pagina.open(ft.SnackBar(
                ft.Text("Faltan datos del titular"), bgcolor="red"
            ))
            return

        sesion = SesionLocal()
        try:
            # 1. Procesar huésped titular y acompañantes
            titular = self.obtener_o_crear_huesped(
                sesion, self.campo_documento.value,
                self.campo_nombre.value, self.campo_apellido.value, es_titular=True,
            )
            lista_huespedes = [titular]

            for fila in self.controles_acompanantes:
                doc    = fila.controls[0].value
                nombre = fila.controls[1].value
                apell  = fila.controls[2].value
                if doc and nombre:
                    acomp = self.obtener_o_crear_huesped(sesion, doc, nombre, apell, es_titular=False)
                    lista_huespedes.append(acomp)

            # 2. Cambiar estado de la habitación a OCUPADA
            habitacion_bd = sesion.query(Habitacion).filter(
                Habitacion.id == self.habitacion.id
            ).first()
            habitacion_bd.estado = EstadoHabitacion.OCCUPIED

            # 3. Calcular noches y total
            fecha_entrada = datetime.strptime(self.campo_entrada.value, "%Y-%m-%d")
            fecha_salida  = datetime.strptime(self.campo_salida.value,  "%Y-%m-%d")
            noches        = max(1, (fecha_salida - fecha_entrada).days)
            precio_noche  = (
                habitacion_bd.precio_actual_usd
                if habitacion_bd.precio_actual_usd
                else habitacion_bd.precio_base_usd
            )
            self.total_calculado = noches * precio_noche

            # 4. Crear la estadía
            # El crédito previo permanece en Huesped.credito_usd.
            # Estadia.deposito_usd ya no se usa para saldo a favor.
            self.estadia_actual = Estadia(
                habitacion_id = habitacion_bd.id,
                entrada       = fecha_entrada,
                salida        = fecha_salida,
                activa        = True,
                deposito_usd  = 0.0,
            )
            self.estadia_actual.huespedes = lista_huespedes
            sesion.add(self.estadia_actual)
            sesion.flush()  # obtener el ID de la estadía antes del commit

            # 5. Crear la línea de cuenta inicial (hospedaje)
            config      = leer_config_financiera(sesion)
            factor_iva  = config.porcentaje_iva / 100
            monto_base  = noches * precio_noche
            from decimal import Decimal, ROUND_HALF_UP
            _D = lambda x: Decimal(str(x))
            monto_total = float((_D(monto_base) * (1 + _D(factor_iva))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            ))
            sesion.add(LineaCuenta(
                estadia_id = self.estadia_actual.id,
                tipo       = TipoLinea.HOSPEDAJE,
                concepto   = (
                    f'Hospedaje — Hab. {habitacion_bd.numero} '
                    f'({noches} noche{"s" if noches > 1 else ""}) '
                    f'del {fecha_entrada.strftime("%d/%m/%Y")} '
                    f'al {fecha_salida.strftime("%d/%m/%Y")}'
                ),
                monto_usd  = monto_total,
                cancelada  = False,
            ))

            # 6. Si el titular tiene deuda de estadías anteriores (credito_usd < 0),
            #    cargarla automáticamente como línea de saldo pendiente.
            titular_bd_fresco = sesion.get(Huesped, titular.id)
            if titular_bd_fresco and (titular_bd_fresco.credito_usd or 0.0) < -0.01:
                deuda_anterior = abs(titular_bd_fresco.credito_usd)
                sesion.add(LineaCuenta(
                    estadia_id = self.estadia_actual.id,
                    tipo       = TipoLinea.SALDO_PENDIENTE,
                    concepto   = f"Deuda de estadías anteriores",
                    monto_usd  = round(deuda_anterior, 2),
                    cancelada  = False,
                ))
                # Limpiar la deuda del perfil (ahora está como línea de cuenta)
                titular_bd_fresco.credito_usd = 0.0

            sesion.commit()
            sesion.refresh(self.estadia_actual)

            self.total_calculado = monto_total
            self.pagina.close(self.dialogo)
            self.preguntar_por_pago()

        except Exception as error:
            sesion.rollback()
            self.pagina.open(ft.SnackBar(
                ft.Text(f"Error en Check-In: {error}"), bgcolor="red"
            ))
        finally:
            sesion.close()

    def preguntar_por_pago(self):
        """
        Muestra un diálogo de confirmación para decidir si cobrar
        inmediatamente o dejar el pago pendiente.
        """
        def ir_a_cobrar(evento):
            self.pagina.close(dialogo_confirmacion)
            modulo_pago = DialogoPago(
                self.pagina,
                self.estadia_actual,
                self.total_calculado,
                al_completar=self.al_completar,
            )
            modulo_pago.mostrar()

        def omitir_pago(evento):
            self.pagina.close(dialogo_confirmacion)
            if self.al_completar:
                self.al_completar()

        dialogo_confirmacion = ft.AlertDialog(
            modal=True,
            title=ft.Text("Estadía Registrada"),
            content=ft.Text(
                f"Total estimado Hab. {self.habitacion.numero}: "
                f"$ {self.total_calculado:.2f}\n¿Desea registrar el pago ahora?"
            ),
            actions=[
                ft.TextButton("Omitir",  on_click=omitir_pago),
                ft.ElevatedButton(
                    "Cobrar", bgcolor=ft.Colors.GREEN_700, color="white",
                    on_click=ir_a_cobrar,
                ),
            ],
        )
        self.pagina.open(dialogo_confirmacion)

    def obtener_o_crear_huesped(self, sesion, documento, nombre, apellido, es_titular: bool) -> Huesped:
        """
        Busca un huésped por documento. Si no existe lo crea.
        Si es el titular, actualiza también sus datos personales completos.
        """
        huesped = sesion.query(Huesped).filter(Huesped.documento == documento).first()
        if not huesped:
            huesped = Huesped(documento=documento, nombre=nombre, apellido=apellido)
            sesion.add(huesped)
        else:
            huesped.nombre   = nombre
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
            huesped.profesion    = self.campo_profesion.value
            huesped.telefono     = self.campo_telefono.value
            huesped.vehiculo     = self.campo_vehiculo.value

        sesion.flush()  # Asigna el id sin hacer commit todavía
        return huesped

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DEL DIÁLOGO
    # ─────────────────────────────────────────────────────────────────────────

    def construir(self) -> ft.AlertDialog:
        return ft.AlertDialog(
            title=ft.Text(f"Check-In — Habitación {self.habitacion.numero}"),
            content=ft.Container(
                width=700,
                content=ft.Column([
                    ft.Row([self.campo_entrada, self.campo_salida]),
                    ft.Divider(),
                    ft.Text("Datos del Titular", weight="bold", color="blue"),
                    self.campo_documento,
                    ft.Row([self.campo_nombre,    self.campo_apellido]),
                    ft.Row([self.campo_fecha_nac, self.campo_nacionalidad]),
                    ft.Row([self.campo_profesion, self.campo_telefono]),
                    self.campo_vehiculo,
                    ft.Divider(),
                    ft.Row([
                        ft.Text("Acompañantes", weight="bold", color="blue"),
                        self.btn_agregar_acompanante,
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    self.contenedor_acompanantes,
                ], scroll=ft.ScrollMode.AUTO, tight=True, spacing=15),
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                self.btn_guardar,
            ],
        )

    def mostrar(self):
        """Construye y abre el diálogo de check-in."""
        self.dialogo = self.construir()
        self.pagina.open(self.dialogo)