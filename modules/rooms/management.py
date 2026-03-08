# modules/rooms/management.py

import flet as ft
from datetime import date
from database.models import Habitacion, EstadoHabitacion, Estadia, LineaCuenta
from database.connection import SesionLocal
from sqlalchemy import cast, Integer
from sqlalchemy.orm import selectinload


class GridHabitaciones:
    """
    Cuadrícula visual del mapa de habitaciones.
    Cada habitación se representa como una tarjeta de color según su estado.
    Al hacer clic en una tarjeta se dispara el callback al_hacer_clic.
    """

    def __init__(self, estado_app: dict, al_hacer_clic):
        self.estado_app   = estado_app
        self.al_hacer_clic = al_hacer_clic
        self.contenedor_grid = ft.Column(
            spacing=15, scroll=ft.ScrollMode.AUTO, expand=True
        )
        # Poblar con habitaciones por defecto (2–40) si la BD está vacía
        self.crear_habitaciones_iniciales()

    def construir(self) -> ft.Column:
        """Construye y retorna la cuadrícula completa con todas las habitaciones."""
        habitaciones = self.obtener_habitaciones()
        self.contenedor_grid.controls.clear()

        fila_tarjetas = ft.Row(
            controls=[self.crear_tarjeta_habitacion(h) for h in habitaciones],
            spacing=15,
            run_spacing=15,
            alignment=ft.MainAxisAlignment.CENTER,
            wrap=True,
        )

        bloque_centrado = ft.Container(
            content=fila_tarjetas,
            alignment=ft.alignment.center,
            padding=ft.padding.all(20),
            expand=True,
        )

        self.contenedor_grid.controls.append(bloque_centrado)
        return self.contenedor_grid

    def obtener_habitaciones(self) -> list:
        """
        Consulta todas las habitaciones ordenadas numéricamente.
        Usa eager loading para evitar consultas N+1 al mostrar el huésped activo.
        """
        sesion = SesionLocal()
        try:
            habitaciones = (
                sesion.query(Habitacion)
                .options(
                    selectinload(Habitacion.estadias_activas)
                    .selectinload(Estadia.huespedes),
                    selectinload(Habitacion.estadias_activas)
                    .selectinload(Estadia.lineas_cuenta),
                )
                .order_by(cast(Habitacion.numero, Integer))
                .all()
            )
            return habitaciones
        except Exception as error:
            print(f"❌ Error en obtener_habitaciones: {error}")
            # Fallback sin eager loading si falla
            return sesion.query(Habitacion).order_by(cast(Habitacion.numero, Integer)).all()
        finally:
            sesion.close()

    def crear_tarjeta_habitacion(self, habitacion: Habitacion) -> ft.Container:
        """
        Crea la tarjeta visual de una habitación.

        Señales visuales adicionales para habitaciones OCCUPIED:
          · Fondo AMARILLO   → tiene al menos una LineaCuenta sin cancelar
                               (cuenta pendiente de cobro).
          · Badge 🔔 (rojo)  → la fecha de salida de la estadía activa es HOY
                               (debe hacer checkout antes de que termine el día).
          Ambas señales pueden mostrarse simultáneamente.
        """
        try:
            estilos_por_estado = {
                EstadoHabitacion.FREE: {
                    "fondo":    ft.Colors.GREEN_50,
                    "acento":   ft.Colors.GREEN_700,
                    "icono":    ft.Icons.BED_OUTLINED,
                    "etiqueta": "DISPONIBLE",
                },
                EstadoHabitacion.OCCUPIED: {
                    "fondo":    ft.Colors.RED_50,
                    "acento":   ft.Colors.RED_800,
                    "icono":    ft.Icons.PERSON,
                    "etiqueta": "OCUPADA",
                },
                EstadoHabitacion.RESERVED: {
                    "fondo":    ft.Colors.AMBER_50,
                    "acento":   ft.Colors.AMBER_800,
                    "icono":    ft.Icons.EVENT_AVAILABLE,
                    "etiqueta": "RESERVADA",
                },
                EstadoHabitacion.CLEANING: {
                    "fondo":    ft.Colors.CYAN_50,
                    "acento":   ft.Colors.CYAN_800,
                    "icono":    ft.Icons.CLEANING_SERVICES,
                    "etiqueta": "LIMPIEZA",
                },
                EstadoHabitacion.MAINTENANCE: {
                    "fondo":    ft.Colors.BLUE_GREY_50,
                    "acento":   ft.Colors.BLUE_GREY_800,
                    "icono":    ft.Icons.BUILD_CIRCLE_OUTLINED,
                    "etiqueta": "MTTO",
                },
            }

            estilo = estilos_por_estado.get(
                habitacion.estado, estilos_por_estado[EstadoHabitacion.FREE]
            )

            # ── Calcular señales dinámicas (solo para habitaciones OCCUPIED) ──
            tiene_pendiente = False   # → fondo amarillo
            sale_hoy        = False   # → badge 🔔
            nombre_huesped  = "---"

            if habitacion.estado == EstadoHabitacion.OCCUPIED:
                estadia_activa = (
                    habitacion.estadias_activas[0]
                    if habitacion.estadias_activas else None
                )
                if estadia_activa:
                    # Cuenta pendiente: al menos una línea no cancelada
                    tiene_pendiente = any(
                        not lc.cancelada
                        for lc in (estadia_activa.lineas_cuenta or [])
                    )

                    # Sale hoy: comparamos solo la parte de fecha.
                    # salida puede ser datetime o date según cómo SQLAlchemy
                    # deserializa el valor — usamos hasattr para cubrirlo.
                    if estadia_activa.salida is not None:
                        salida_date = (
                            estadia_activa.salida.date()
                            if hasattr(estadia_activa.salida, "date")
                            else estadia_activa.salida
                        )
                        sale_hoy = (salida_date == date.today())

                    # Nombre del titular: primer huésped de la estadía activa
                    if estadia_activa.huespedes:
                        titular = estadia_activa.huespedes[0]
                        # Mostramos solo el primer nombre para que quepa en la card
                        nombre_huesped = titular.nombre.split()[0] if titular.nombre else "Huésped"

            # Cuando hay cuenta pendiente reemplazamos el fondo rojo por amarillo
            # pero conservamos el acento rojo para borde, barra y número de hab.
            fondo_efectivo = (
                ft.Colors.YELLOW_100
                if tiene_pendiente and habitacion.estado == EstadoHabitacion.OCCUPIED
                else estilo["fondo"]
            )

            # ── Badge "Sale hoy" — esquina superior derecha del Stack ─────────
            # Usamos un Container posicionado en el Stack para que flote sobre
            # el contenido sin afectar el layout de la Column interior.
            badge_sale_hoy = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE,
                            size=11, color=ft.Colors.WHITE),
                    ft.Text("HOY", size=8, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                ], spacing=2, tight=True),
                bgcolor=ft.Colors.ORANGE_700,
                padding=ft.padding.symmetric(horizontal=5, vertical=3),
                border_radius=ft.border_radius.only(
                    top_right=10, bottom_left=8
                ),
                right=0,
                top=0,
                visible=sale_hoy,
            )

            # ── Chip "$ Pendiente" — dentro de la columna central ─────────────
            chip_pendiente = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_ROUNDED,
                            size=10, color=ft.Colors.ORANGE_900),
                    ft.Text("PENDIENTE", size=7, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.ORANGE_900),
                ], spacing=2, tight=True),
                bgcolor=ft.Colors.ORANGE_100,
                padding=ft.padding.symmetric(horizontal=5, vertical=2),
                border_radius=6,
                border=ft.border.all(1, ft.Colors.ORANGE_300),
                visible=tiene_pendiente,
            )

            return ft.Container(
                width=130,
                height=150,
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(
                    # Borde más grueso y amarillo dorado cuando hay pendiente
                    2.5 if tiene_pendiente else 1.5,
                    ft.Colors.YELLOW_700
                    if tiene_pendiente and habitacion.estado == EstadoHabitacion.OCCUPIED
                    else (
                        estilo["acento"]
                        if habitacion.estado != EstadoHabitacion.FREE
                        else ft.Colors.GREY_200
                    ),
                ),
                border_radius=12,
                ink=True,
                on_click=lambda _, h=habitacion: self.al_hacer_clic(h),
                on_hover=lambda e, ac=estilo["acento"], pend=tiene_pendiente: self.al_pasar_cursor(e, ac, pend),
                shadow=ft.BoxShadow(
                    spread_radius=1,
                    blur_radius=3,
                    color=ft.Colors.BLACK12,
                    offset=ft.Offset(1, 4),
                ),
                content=ft.Stack([
                    # Capa de color de fondo (amarillo si pendiente, color estado si no)
                    ft.Container(bgcolor=fondo_efectivo, border_radius=12),
                    # Contenido principal
                    ft.Column([
                        # Fila superior: número de hab y tipo
                        ft.Container(
                            padding=ft.padding.only(left=10, right=10, top=10),
                            content=ft.Row([
                                ft.Text(
                                    f"{habitacion.numero}", size=20,
                                    weight=ft.FontWeight.W_800,
                                    color=estilo["acento"],
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        habitacion.tipo.upper(), size=7,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLACK54,
                                    ),
                                    bgcolor=ft.Colors.with_opacity(
                                        0.1, estilo["acento"]
                                    ),
                                    padding=ft.padding.symmetric(
                                        horizontal=5, vertical=2
                                    ),
                                    border_radius=5,
                                ),
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ),
                        # Ícono central, nombre del huésped y chip pendiente
                        ft.Container(
                            expand=True,
                            alignment=ft.alignment.center,
                            content=ft.Column([
                                ft.Icon(estilo["icono"],
                                        color=estilo["acento"], size=28),
                                ft.Text(
                                    nombre_huesped.upper(), size=9,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.BLACK87,
                                    text_align=ft.TextAlign.CENTER,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                chip_pendiente,
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                               spacing=2),
                        ),
                        # Barra de estado inferior
                        ft.Container(
                            width=130,
                            bgcolor=estilo["acento"],
                            padding=ft.padding.all(4),
                            border_radius=ft.border_radius.only(
                                bottom_left=10, bottom_right=10
                            ),
                            content=ft.Text(
                                estilo["etiqueta"], size=9,
                                weight=ft.FontWeight.W_700,
                                color=ft.Colors.WHITE,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ),
                    ], spacing=0),
                    # Badge flotante "Sale HOY" — posicionado en el Stack
                    badge_sale_hoy,
                ]),
            )

        except Exception as error:
            print(f"❌ Error al crear tarjeta Hab. {habitacion.numero}: {error}")
            return ft.Container(
                width=130, height=150, bgcolor=ft.Colors.RED_100,
                content=ft.Text("Error", color=ft.Colors.RED_900),
            )

    def crear_habitaciones_iniciales(self):
        """
        Crea las habitaciones del 2 al 40 con tipos y precios predeterminados.
        Solo se ejecuta si la tabla de habitaciones está vacía.
        """
        sesion = SesionLocal()
        try:
            if sesion.query(Habitacion).count() > 0:
                return  # Ya hay habitaciones, no hace falta crear

            tipos  = ["Estándar", "Doble", "Suite", "Familiar"]
            precios = {"Estándar": 50.0, "Doble": 75.0, "Suite": 120.0, "Familiar": 90.0}

            for i in range(2, 41):
                tipo_hab = tipos[i % len(tipos)]
                sesion.add(Habitacion(
                    numero           = str(i),
                    piso             = (i // 10) + 1,
                    tipo             = tipo_hab,
                    estado           = EstadoHabitacion.FREE,
                    precio_base_usd  = precios.get(tipo_hab, 50.0),
                    precio_actual_usd= precios.get(tipo_hab, 50.0),
                    capacidad_maxima = 4 if tipo_hab == "Familiar" else 2,
                    descripcion      = f"Habitación {i}",
                ))
            sesion.commit()
            print("✅ Habitaciones 2–40 creadas correctamente")

        except Exception as error:
            print(f"❌ Error al crear habitaciones: {error}")
            sesion.rollback()
        finally:
            sesion.close()

    def al_pasar_cursor(self, evento, color_acento, tiene_pendiente=False):
        """Aplica efecto de elevación al pasar el cursor sobre una tarjeta.
        Si la tarjeta tiene cuenta pendiente, el halo de hover usa amarillo dorado
        en lugar del acento del estado para mantener la coherencia visual."""
        color_hover = (
            ft.Colors.YELLOW_700 if tiene_pendiente else color_acento
        )
        evento.control.shadow = ft.BoxShadow(
            spread_radius=1,
            blur_radius=3,
            color=(
                ft.Colors.with_opacity(0.25, color_hover)
                if evento.data == "true"
                else ft.Colors.BLACK12
            ),
            offset=ft.Offset(2, 5) if evento.data == "true" else ft.Offset(1, 4),
        )
        #evento.control.scale = 1.03 if evento.data == "true" else 1.0
        evento.control.update()