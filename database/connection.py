# database/connection.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# URL de conexión a la base de datos (SQLite por defecto)
URL_BASE_DATOS = os.getenv("DATABASE_URL", "sqlite:///hotel.db")

# Motor de la base de datos
motor = create_engine(
    URL_BASE_DATOS,
    connect_args={"check_same_thread": False} if "sqlite" in URL_BASE_DATOS else {},
    echo=False  # False en producción: evita inundar la consola con cada SQL
)

# Fábrica de sesiones: cada módulo crea su sesión con SesionLocal()
SesionLocal = sessionmaker(autocommit=False, autoflush=False, bind=motor)

# Base declarativa para todos los modelos ORM
Base = declarative_base()


def obtener_sesion_bd():
    """Generador de sesión para inyección de dependencias (uso con FastAPI/routers)."""
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


def inicializar_bd():
    """Crea todas las tablas en la base de datos si no existen."""
    Base.metadata.create_all(bind=motor)
    print("✅ Base de datos inicializada correctamente")