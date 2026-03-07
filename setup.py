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
    Caja, Pago, CargoExtra, Huesped, Estadia, Turno
)
from sqlalchemy.orm import sessionmaker
from utils.helpers import hashear_contrasena
from datetime import datetime


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
            saldo_principal_usd  = 0.0,    # Las ventas arrancan en $0
            saldo_principal_bs   = 0.0,
            caja_chica_usd       = 100.0,  # Fondo fijo para dar vueltos
            caja_chica_bs        = 8000.0,
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

        # ── 4. Habitaciones del 2 al 40 ──────────────────────────────────────
        print("Generando habitaciones (2 al 40)...")
        tipos_habitacion = ["Estándar", "Doble", "Suite", "Familiar"]
        precios_por_tipo = {
            "Estándar": 43.1034,
            "Doble":    75.0,
            "Suite":   120.0,
            "Familiar": 90.0,
        }

        for numero in range(2, 41):
            tipo     = tipos_habitacion[numero % len(tipos_habitacion)]
            precio   = precios_por_tipo.get(tipo, 50.0)
            capacidad = 4 if tipo == "Familiar" else 2

            sesion.add(Habitacion(
                numero            = str(numero),
                piso              = (numero // 10) + 1,
                tipo              = tipo,
                estado            = EstadoHabitacion.FREE,
                precio_base_usd   = precio,
                precio_actual_usd = precio,
                capacidad_maxima  = capacidad,
                descripcion       = f"Habitación {tipo} #{numero}",
                amenidades        = "WiFi, TV, A/A, Agua Caliente",
            ))

        sesion.commit()

        print("\n" + "=" * 45)
        print("BASE DE DATOS PREPARADA CORRECTAMENTE")
        print("=" * 45)
        print(f"  Usuario admin:    admin / admin123")
        print(f"  Caja principal:   $0.00")
        print(f"  Caja chica:       $100.00")
        print(f"  Habitaciones:     39 disponibles (2–40)")
        print(f"  Tasa inicial:     36.50 Bs/$")
        print("=" * 45)

    except Exception as error:
        sesion.rollback()
        print(f"Error crítico durante la inicialización: {error}")
    finally:
        sesion.close()


if __name__ == "__main__":
    print("ADVERTENCIA: Esto borrará todos los datos existentes.")
    respuesta = input("¿Confirmar limpieza y recreación total? (s/N): ")
    if respuesta.lower() == 's':
        reiniciar_base_de_datos()
    else:
        print("Operación cancelada.")