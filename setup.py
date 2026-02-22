# setup.py

"""
Script para reiniciar la base de datos a su estado inicial
Ejecutar: python setup.py
"""

from database.connection import engine, Base
from database.models import User, Room, Configuration, UserRole, RoomStatus
from sqlalchemy.orm import sessionmaker
from utils.helpers import hash_password
import os

def reset_database():
    """Elimina y recrea todas las tablas"""
    print("🗑️  Eliminando tablas existentes...")
    Base.metadata.drop_all(bind=engine)
    
    print("🏗️  Creando nuevas tablas...")
    Base.metadata.create_all(bind=engine)
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Crear usuario admin con el enum correcto
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            full_name="Administrador",
            email="admin@hotel.com",
            role=UserRole.ADMIN  # Usando el enum
        )
        db.add(admin)
        
        # Crear configuración inicial
        configs = [
            Configuration(key="exchange_rate", value="35.50", 
                         description="Tasa de cambio USD/BS"),
            Configuration(key="hotel_name", value="Hotel Paraíso", 
                         description="Nombre del hotel"),
        ]
        db.add_all(configs)
        
        # Crear algunas habitaciones de ejemplo
        for i in range(1, 40):
            if i % 5 == 0:
                status = RoomStatus.OCCUPIED
            elif i % 7 == 0:
                status = RoomStatus.RESERVED
            elif i % 9 == 0:
                status = RoomStatus.CLEANING
            elif i % 11 == 0:
                status = RoomStatus.MAINTENANCE
            else:
                status = RoomStatus.FREE
            
            room = Room(
                number=f"{i:03d}",
                floor=(i - 1) // 13 + 1,
                type="Estándar" if i % 3 != 0 else "Suite",
                status=status,
                base_price_usd=50.0 + (i % 5) * 10,
                current_price_usd=50.0 + (i % 5) * 10,
                max_occupancy=2,
                description=f"Habitación {i:03d}",
                amenities="WiFi, TV, A/A"
            )
            db.add(room)
        
        db.commit()
        print("✅ Base de datos inicializada correctamente")
        print("   Usuario: admin")
        print("   Contraseña: admin123")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("=== Reinicialización del Sistema Hotelero ===")
    response = input("¿Estás seguro? Esto borrará TODOS los datos (s/N): ")
    
    if response.lower() == 's':
        reset_database()
    else:
        print("Operación cancelada")