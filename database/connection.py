# database/connection.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///hotel.db")

# Crear engine
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False  # Cambiado a False: True inundaba la consola con cada consulta SQL en producción
)

# Crear sesión local
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para modelos
Base = declarative_base()

# Función para obtener sesión de BD
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Función para inicializar BD
def init_db():
    """Crea las tablas en la base de datos"""
    Base.metadata.create_all(bind=engine)
    print("✅ Base de datos inicializada correctamente")