"""
setup.py
Script de inicialización / reinicio de la base de datos.
Elimina y recrea todas las tablas con los datos de prueba iniciales.

Uso:
    python setup.py
"""

from database.connection import motor, Base
from database.models import (
    Usuario, Habitacion, Configuracion, RolUsuario, EstadoHabitacion,
    Caja, Huesped, Estadia, Turno, TipoHabitacion,
)
from sqlalchemy.orm import sessionmaker
from utils.helpers import hashear_contrasena
from datetime import datetime
from decimal import Decimal


def reiniciar_base_de_datos():
    """
    Elimina todas las tablas y las recrea desde cero
    con un conjunto de datos iniciales para pruebas.
    """
    print("Eliminando tablas existentes...")
    Base.metadata.drop_all(bind=motor)

    print("Creando nuevas tablas...")
    Base.metadata.create_all(bind=motor)

    FabricaSesion = sessionmaker(bind=motor)
    sesion = FabricaSesion()

    try:
        # ── 1. Usuario administrador por defecto ─────────────────────────────
        print("Creando usuario administrador...")
        admin = Usuario(
            nombre_usuario  = "admin",
            hash_contrasena = hashear_contrasena("admin123"),
            nombre_completo = "Administrador",
            correo          = "admin@hotel.com",
            rol             = RolUsuario.ADMIN,
        )
        sesion.add(admin)

        # ── 2. Estructura de cajas (principal + chica) ───────────────────────
        print("Inicializando estructura de cajas...")
        caja_inicial = Caja(
            saldo_principal_usd  = Decimal("0"),
            saldo_principal_bs   = Decimal("0"),
            caja_chica_usd       = Decimal("100"),
            caja_chica_bs        = Decimal("8000"),
            ultima_actualizacion = datetime.now(),
        )
        sesion.add(caja_inicial)

        # ── 3. Configuración inicial del sistema ─────────────────────────────
        print("Cargando configuración inicial...")
        configuraciones = [
            Configuracion(
                clave       = "exchange_rate",
                valor       = "36.50",
                descripcion = "Tasa de cambio oficial USD/Bs",
            ),
            Configuracion(
                clave       = "hotel_name",
                valor       = "Hotel Paraíso",
                descripcion = "Nombre comercial del hotel",
            ),
            Configuracion(
                clave       = "tax_percentage",
                valor       = "16",
                descripcion = "Porcentaje de impuesto (IVA) aplicado a las facturas",
            ),
        ]
        sesion.add_all(configuraciones)

        # ── 4. Catálogo de tipos de habitación con precios ───────────────────
        print("Creando catálogo de tipos de habitación...")
        tipos_catalogo = [
            TipoHabitacion(
                nombre            = "Estándar",
                precio_base_usd   = Decimal("43.10"),
                precio_actual_usd = Decimal("43.10"),
                capacidad_default = 2,
                descripcion       = "Habitación estándar con amenidades básicas",
            ),
            TipoHabitacion(
                nombre            = "Doble",
                precio_base_usd   = Decimal("75.00"),
                precio_actual_usd = Decimal("75.00"),
                capacidad_default = 2,
                descripcion       = "Habitación doble con cama king size",
            ),
            TipoHabitacion(
                nombre            = "Suite",
                precio_base_usd   = Decimal("120.00"),
                precio_actual_usd = Decimal("120.00"),
                capacidad_default = 2,
                descripcion       = "Suite con sala de estar y vista panorámica",
            ),
            TipoHabitacion(
                nombre            = "Familiar",
                precio_base_usd   = Decimal("90.00"),
                precio_actual_usd = Decimal("90.00"),
                capacidad_default = 4,
                descripcion       = "Habitación familiar con dos camas dobles",
            ),
            TipoHabitacion(
                nombre            = "VIP",
                precio_base_usd   = Decimal("150.00"),
                precio_actual_usd = Decimal("150.00"),
                capacidad_default = 2,
                descripcion       = "Habitación VIP con servicio prioritario",
            ),
            TipoHabitacion(
                nombre            = "Presidencial",
                precio_base_usd   = Decimal("200.00"),
                precio_actual_usd = Decimal("200.00"),
                capacidad_default = 2,
                descripcion       = "Suite presidencial con todas las comodidades",
            ),
        ]
        sesion.add_all(tipos_catalogo)
        sesion.flush()  # obtener IDs antes de usarlos en habitaciones

        # Mapa nombre → objeto para asignar precios a habitaciones
        tipo_map = {t.nombre: t for t in tipos_catalogo}

        # ── 5. Habitaciones del 2 al 40 ──────────────────────────────────────
        print("Generando habitaciones (2 al 40)...")
        rotacion_tipos = ["Estándar", "Doble", "Suite", "Familiar"]

        for numero in range(2, 41):
            nombre_tipo = rotacion_tipos[numero % len(rotacion_tipos)]
            tipo_obj    = tipo_map[nombre_tipo]

            sesion.add(Habitacion(
                numero            = str(numero),
                piso              = (numero // 10) + 1,
                tipo              = tipo_obj.nombre,
                estado            = EstadoHabitacion.FREE,
                precio_base_usd   = tipo_obj.precio_base_usd,
                precio_actual_usd = tipo_obj.precio_actual_usd,
                capacidad_maxima  = tipo_obj.capacidad_default,
                descripcion       = f"Habitación {tipo_obj.nombre} #{numero}",
                amenidades        = "WiFi, TV, A/A, Agua Caliente",
            ))

        sesion.commit()

        print("\n" + "=" * 48)
        print("  BASE DE DATOS PREPARADA CORRECTAMENTE")
        print("=" * 48)
        print(f"  Usuario admin    →  admin / admin123")
        print(f"  Caja principal   →  $0.00  |  Bs. 0,00")
        print(f"  Caja chica       →  $100.00  |  Bs. 8.000,00")
        print(f"  Tasa inicial     →  36.50 Bs/$")
        print(f"  IVA              →  16%")
        print(f"  Tipos creados    →  {len(tipos_catalogo)}")
        print(f"  Habitaciones     →  39 disponibles (2–40)")
        print("=" * 48)

    except Exception as error:
        sesion.rollback()
        print(f"\n❌ Error crítico durante la inicialización: {error}")
        raise
    finally:
        sesion.close()


if __name__ == "__main__":
    print("=" * 48)
    print("  REINICIO TOTAL DE LA BASE DE DATOS")
    print("=" * 48)
    print("⚠  ADVERTENCIA: Esto borrará todos los datos existentes.")
    respuesta = input("\n¿Confirmar limpieza y recreación total? (s/N): ")
    if respuesta.lower() == "s":
        reiniciar_base_de_datos()
    else:
        print("Operación cancelada.")