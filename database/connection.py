# database/connection.py

from sqlalchemy import create_engine, event
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
    connect_args={
        "check_same_thread": False,
        "timeout": 15,          # espera hasta 15s si la BD está bloqueada
    } if "sqlite" in URL_BASE_DATOS else {},
    echo=False,
)

# Activar WAL en cada nueva conexión SQLite.
# WAL (Write-Ahead Logging) permite lecturas y escrituras concurrentes
# sin que se bloqueen entre sí — soluciona "database is locked" cuando
# el dispatcher de Telegram escribe mientras hay una transacción abierta.
if "sqlite" in URL_BASE_DATOS:
    @event.listens_for(motor, "connect")
    def _activar_wal(dbapi_con, _record):
        dbapi_con.execute("PRAGMA journal_mode=WAL")
        dbapi_con.execute("PRAGMA synchronous=NORMAL")
        dbapi_con.execute("PRAGMA busy_timeout=15000")   # 15s en ms

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