"""
Script para reiniciar la base de datos a su estado inicial
Ejecutar: python setup.py
"""

from database.connection import engine, Base
# Importamos desde models (el archivo actualizado)
from database.models import User, Room, Configuration, UserRole, RoomStatus
from sqlalchemy.orm import sessionmaker
from utils.helpers import hash_password

def reset_database():
    """Elimina y recrea todas las tablas"""
    print("🗑️  Eliminando tablas existentes...")
    Base.metadata.drop_all(bind=engine)
    
    print("🏗️  Creando nuevas tablas (incluyendo Huéspedes y Estadías)...")
    Base.metadata.create_all(bind=engine)
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # 1. Crear usuario admin
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            full_name="Administrador",
            email="admin@hotel.com",
            role=UserRole.ADMIN
        )
        db.add(admin)
        
        # 2. Crear configuración inicial
        configs = [
            Configuration(key="exchange_rate", value="35.50", 
                         description="Tasa de cambio USD/BS"),
            Configuration(key="hotel_name", value="Hotel Paraíso", 
                         description="Nombre del hotel"),
        ]
        db.add_all(configs)
        
        # 3. Crear habitaciones del 2 al 40
        print("🏨 Generando habitaciones del 2 al 40...")
        types = ["Estándar", "Doble", "Suite", "Familiar"]
        
        for i in range(2, 41):
            room_type = types[i % len(types)]
            
            # Lógica de estados iniciales para la demo
            if i % 8 == 0:
                status = RoomStatus.OCCUPIED
            elif i % 15 == 0:
                status = RoomStatus.MAINTENANCE
            elif i % 10 == 0:
                status = RoomStatus.CLEANING
            else:
                status = RoomStatus.FREE
            
            # Precios sugeridos por tipo
            prices = {"Estándar": 50.0, "Doble": 75.0, "Suite": 120.0, "Familiar": 90.0}
            base_p = prices.get(room_type, 50.0)

            room = Room(
                number=str(i), # Formato simple "2", "3", etc.
                floor=(i // 10) + 1,
                type=room_type,
                status=status,
                base_price_usd=base_p,
                current_price_usd=base_p,
                max_occupancy=4 if room_type == "Familiar" else 2,
                description=f"Habitación {room_type} #{i}",
                amenities="WiFi, TV, A/A"
            )
            db.add(room)
        
        db.commit()
        print("\n✅ Sistema reiniciado con éxito")
        print("-------------------------------")
        print("  Rango habitaciones: 2 al 40")
        print("  Usuario: admin / admin123")
        print("-------------------------------")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error durante la inicialización: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("=== REINICIO MAESTRO DE BASE DE DATOS ===")
    print("Atención: Esto borrará todos los huéspedes, usuarios y habitaciones.")
    response = input("¿Confirmar limpieza total? (s/N): ")
    
    if response.lower() == 's':
        reset_database()
    else:
        print("Operación abortada.")