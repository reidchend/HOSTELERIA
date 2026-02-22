# database/models.py

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from database.connection import Base

# Enums para estados
class RoomStatus(enum.Enum):
    FREE = "libre"
    OCCUPIED = "ocupada"
    RESERVED = "reservada"
    CLEANING = "aseo"
    MAINTENANCE = "mantenimiento"

class UserRole(enum.Enum):
    ADMIN = "ADMIN"  # Cambiado a mayúsculas para consistencia
    SUPERVISOR = "SUPERVISOR"
    OPERATOR = "OPERATOR"

# Modelo de Usuario
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100))
    role = Column(Enum(UserRole), default=UserRole.OPERATOR)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<User {self.username}>"

# Modelo de Habitación
class Room(Base):
    __tablename__ = 'rooms'
    
    id = Column(Integer, primary_key=True)
    number = Column(String(10), unique=True, nullable=False)
    floor = Column(Integer)
    type = Column(String(50), default="Estándar")
    status = Column(Enum(RoomStatus), default=RoomStatus.FREE)
    base_price_usd = Column(Float, nullable=False, default=50.0)
    current_price_usd = Column(Float, nullable=False)
    max_occupancy = Column(Integer, default=2)
    description = Column(String(200))
    amenities = Column(String(500))
    last_cleaned = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<Room {self.number} - {self.status.value}>"

# Modelo de Configuración
class Configuration(Base):
    __tablename__ = 'configurations'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(String(500))
    description = Column(String(200))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<Config {self.key}={self.value}>"