"""
setup.py
Script de inicialización / reinicio de la base de datos.
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
    print("Eliminando tablas existentes...")
    Base.metadata.drop_all(bind=motor)

    print("Creando nuevas tablas...")
    Base.metadata.create_all(bind=motor)

    FabricaSesion = sessionmaker(bind=motor)
    sesion = FabricaSesion()

    try:
        # ── 1. Usuario administrador ──────────────────────────────────────────
        print("Creando usuario administrador...")
        sesion.add(Usuario(
            nombre_usuario  = "admin",
            hash_contrasena = hashear_contrasena("admin123"),
            nombre_completo = "Administrador",
            correo          = "admin@hotel.com",
            rol             = RolUsuario.ADMIN,
        ))

        # ── 2. Cajas ──────────────────────────────────────────────────────────
        print("Inicializando cajas...")
        sesion.add(Caja(
            saldo_principal_usd  = Decimal("0"),
            saldo_principal_bs   = Decimal("0"),
            caja_chica_usd       = Decimal("100"),
            caja_chica_bs        = Decimal("8000"),
            ultima_actualizacion = datetime.now(),
        ))

        # ── 3. Configuración ──────────────────────────────────────────────────
        print("Cargando configuración inicial...")
        sesion.add_all([
            Configuracion(
                clave       = "exchange_rate",
                valor       = "36.50",
                descripcion = "Tasa de cambio oficial USD/Bs",
            ),
            Configuracion(
                clave       = "hotel_name",
                valor       = "La Posada de Daniel C.A.",
                descripcion = "Nombre comercial del hotel",
            ),
            Configuracion(
                clave       = "tax_percentage",
                valor       = "16",
                descripcion = "Porcentaje de IVA aplicado a las facturas",
            ),
            Configuracion(
                clave       = "google_sheet_id",
                valor       = "1Yn4VVUl0vHASnoZtyGUTSqrkob_XxxMyKvbhsEywwvw",
                descripcion = "ID de la Google Sheet de reservaciones web",
            ),
            Configuracion(
                clave       = "google_script_url",
                valor       = "https://script.google.com/macros/s/AKfycbw0gMWrVJ67BOeiHJsxAq5s_fgVObgtpHJqA-joTuytSAAWNgwPjU1_vIgTKghcu_Bh/exec",
                descripcion = "URL del Google Apps Script Web App (reservaciones)",
            ),
        ])

        # ── 4. Tipos de habitación ────────────────────────────────────────────
        print("Creando tipos de habitación...")
        tipos_catalogo = [
            TipoHabitacion(
                nombre            = "MATRIMONIAL",
                precio_base_usd   = Decimal("25.86"),
                precio_actual_usd = Decimal("25.86"),
                capacidad_default = 2,
                descripcion       = "Habitación matrimonial con amenidades básicas",
            ),
            TipoHabitacion(
                nombre            = "DOBLE",
                precio_base_usd   = Decimal("30.17"),
                precio_actual_usd = Decimal("30.17"),
                capacidad_default = 2,
                descripcion       = "Habitación doble",
            ),
            TipoHabitacion(
                nombre            = "SUITE",
                precio_base_usd   = Decimal("30.17"),
                precio_actual_usd = Decimal("30.17"),
                capacidad_default = 2,
                descripcion       = "Suite con sala de estar",
            ),
            TipoHabitacion(
                nombre            = "TRIPLE",
                precio_base_usd   = Decimal("34.48"),
                precio_actual_usd = Decimal("34.48"),
                capacidad_default = 3,
                descripcion       = "Habitación triple",
            ),
            TipoHabitacion(
                nombre            = "QUINTUPLE",
                precio_base_usd   = Decimal("38.79"),
                precio_actual_usd = Decimal("38.79"),
                capacidad_default = 5,
                descripcion       = "Habitación quíntuple",
            ),
            TipoHabitacion(
                nombre            = "INDIVIDUAL",
                precio_base_usd   = Decimal("17.24"),
                precio_actual_usd = Decimal("17.24"),
                capacidad_default = 1,
                descripcion       = "Habitación individual",
            ),
        ]
        sesion.add_all(tipos_catalogo)
        sesion.flush()

        tipo_map = {t.nombre: t for t in tipos_catalogo}

        # ── 5. Habitaciones 2–40 ──────────────────────────────────────────────
        print("Generando habitaciones (2 al 40) con asignación específica...")
        
        # Definición de listas según tu requerimiento
        dobles      = [12, 16, 28, 38, 39, 40]
        triples     = [25, 27, 29, 30]
        quintuple   = [35]
        individual  = [36]

        for numero in range(2, 41):
            # Lógica de asignación basada en las listas
            if numero in dobles:
                tipo_nombre = "DOBLE"
            elif numero in triples:
                tipo_nombre = "TRIPLE"
            elif numero in quintuple:
                tipo_nombre = "QUINTUPLE"
            elif numero in individual:
                tipo_nombre = "INDIVIDUAL"
            else:
                tipo_nombre = "MATRIMONIAL" # El resto por defecto

            t = tipo_map[tipo_nombre]
            
            sesion.add(Habitacion(
                numero            = str(numero),
                piso              = (numero // 10) + 1,
                tipo              = t.nombre,
                estado            = EstadoHabitacion.FREE,
                precio_base_usd   = t.precio_base_usd,
                precio_actual_usd = t.precio_actual_usd,
                capacidad_maxima  = t.capacidad_default,
                descripcion       = f"Habitación {t.nombre} #{numero}",
                amenidades        = "WiFi, TV, A/A, Agua Caliente",
            ))

        sesion.commit()

        print("\n" + "=" * 50)
        print("  BASE DE DATOS PREPARADA CORRECTAMENTE")
        print("=" * 50)
        print(f"  Usuario admin    →  admin / admin123")
        print(f"  Hotel            →  La Posada de Daniel C.A.")
        print(f"  Caja chica       →  $100.00  |  Bs. 8.000,00")
        print(f"  Tasa inicial     →  36.50 Bs/$  |  IVA: 16%")
        print(f"  Tipos creados    →  {len(tipos_catalogo)}")
        print(f"  Habitaciones     →  39 disponibles (2–40)")
        print(f"  Google Sheet     →  ✅ configurado")
        print(f"  Apps Script      →  ✅ configurado")
        print("=" * 50)

    except Exception as error:
        sesion.rollback()
        print(f"\n❌ Error: {error}")
        raise
    finally:
        sesion.close()


if __name__ == "__main__":
    print("=" * 50)
    print("  REINICIO TOTAL DE LA BASE DE DATOS")
    print("=" * 50)
    print("⚠  Esto borrará todos los datos existentes.")
    respuesta = input("\n¿Confirmar? (s/N): ")
    if respuesta.lower() == "s":
        reiniciar_base_de_datos()
    else:
        print("Operación cancelada.")