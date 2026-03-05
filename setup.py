"""
Script para reiniciar la base de datos a su estado inicial
Ejecutar: python setup.py
"""

from database.connection import engine, Base
# Importamos todos los modelos incluyendo Shift para que se cree la tabla
from database.models import (
    User, Room, Configuration, UserRole, RoomStatus, 
    CashDrawer, Payment, ExtraCharge, Guest, Stay, Shift
)
from sqlalchemy.orm import sessionmaker
from utils.helpers import hash_password
from datetime import datetime

def reset_database():
    """Elimina y recrea todas las tablas con soporte para Doble Caja y Turnos"""
    print("🗑️  Eliminando tablas existentes...")
    Base.metadata.drop_all(bind=engine)
    
    print("🏗️  Creando nuevas tablas (Finanzas v2, Caja Doble, Turnos)...")
    Base.metadata.create_all(bind=engine)
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # 1. Crear usuario admin
        print("👤 Creando usuario administrador...")
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            full_name="Administrador",
            email="admin@hotel.com",
            role=UserRole.ADMIN
        )
        db.add(admin)
        
        # 2. Inicializar Caja Doble
        print("💵 Inicializando Estructura de Cajas (Principal y Chica)...")
        caja_inicial = CashDrawer(
            main_balance_usd=0.0,    # Ventas empiezan en 0
            main_balance_bs=0.0,
            petty_cash_usd=100.0,    # Fondo fijo para vueltos
            petty_cash_bs=8000.0,
            last_update=datetime.now()
        )
        db.add(caja_inicial)
        
        # 3. Crear configuración inicial
        print("⚙️  Cargando configuraciones y tasa de cambio...")
        configs = [
            Configuration(
                key="exchange_rate", 
                value="10", 
                description="Tasa de cambio oficial USD/BS"
            ),
            Configuration(
                key="hotel_name", 
                value="La Posada de Daniel", 
                description="Nombre comercial del hotel"
            ),
            Configuration(
                key="tax_percentage", 
                value="16", 
                description="Porcentaje de impuesto aplicado"
            ),
        ]
        db.add_all(configs)
        
        # 4. Crear habitaciones del 2 al 40
        print("🏨 Generando habitaciones (2 al 40)...")
        types = ["Estándar", "Doble", "Suite", "Familiar"]
        prices = {"Estándar": 43.10, "Doble": 75.0, "Suite": 120.0, "Familiar": 90.0}
        
        for i in range(2, 41):
            room_type = types[i % len(types)]
            base_p = prices.get(room_type, 50.0)
            
            # Habitaciones libres para la prueba de flujo
            status = RoomStatus.FREE

            room = Room(
                number=str(i),
                floor=(i // 10) + 1,
                type=room_type,
                status=status,
                base_price_usd=base_p,
                current_price_usd=base_p,
                max_occupancy=4 if room_type == "Familiar" else 2,
                description=f"Habitación {room_type} #{i}",
                amenities="WiFi, TV, A/A, Agua Caliente"
            )
            db.add(room)
        
        db.commit()
        print("\n" + "="*40)
        print("✅ BASE DE DATOS PREPARADA PARA PRUEBA DE FLUJO")
        print("="*40)
        print(f"Caja Principal: $0.00")
        print(f"Caja Chica (Vueltos): $100.00")
        print(f"Habitaciones: 39 Disponibles")
        print("="*40)
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error crítico durante la inicialización: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("⚠️  ADVERTENCIA: REINICIO TOTAL")
    response = input("¿Confirmar limpieza y recreación total? (s/N): ")
    
    if response.lower() == 's':
        reset_database()
    else:
        print("❌ Operación cancelada.")