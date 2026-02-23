from sqlalchemy import Column, Integer, String, Float, Enum, Boolean, DateTime, Date, ForeignKey, Table
from sqlalchemy.orm import relationship
from database.connection import Base
import enum
from datetime import datetime

# 1. ENUMS (No dependen de nadie)
class UserRole(enum.Enum):
    ADMIN = "admin"
    RECEPCIONIST = "receptionist"

class RoomStatus(enum.Enum):
    FREE = "free"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    CLEANING = "cleaning"
    MAINTENANCE = "maintenance"

# 2. TABLA INTERMEDIA (Definida antes que las clases que la usan)
stay_guests = Table(
    'stay_guests',
    Base.metadata,
    Column('stay_id', Integer, ForeignKey('stays.id')),
    Column('guest_id', Integer, ForeignKey('guests.id'))
)

# 3. CLASE GUEST (No depende de Stay ni de Room)
class Guest(Base):
    __tablename__ = "guests"
    id = Column(Integer, primary_key=True)
    document_id = Column(String(20), unique=True, index=True)
    first_name = Column(String(50))
    last_name = Column(String(50))
    birth_date = Column(Date, nullable=True)
    nationality = Column(String(50))
    profession = Column(String(50))
    phone = Column(String(20))
    vehicle_info = Column(String(100), nullable=True)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

# 4. CLASE ROOM (Depende de Stay, por eso usamos "Stay" con comillas)
class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    number = Column(String(10), unique=True, index=True)
    floor = Column(Integer)
    type = Column(String(50))
    status = Column(Enum(RoomStatus), default=RoomStatus.FREE)
    base_price_usd = Column(Float)
    current_price_usd = Column(Float)
    max_occupancy = Column(Integer, default=2)
    description = Column(String(200))
    amenities = Column(String(200))
    last_cleaned = Column(DateTime, default=datetime.now)

    # Relación usando string para evitar NameError
    active_stays = relationship("Stay", back_populates="room")

    # Dentro de la clase Room en database/models.py

    @property
    def current_guest_name(self):
        """Versión ultra-segura para evitar NameError"""
        try:
            # En lugar de buscar la clase 'Stay', miramos si la relación ya tiene datos
            if hasattr(self, "active_stays") and self.active_stays:
                # Buscamos la estadía marcada como activa
                for stay in self.active_stays:
                    if getattr(stay, "is_active", False):
                        # Si tiene huéspedes, devolvemos el nombre del primero
                        if hasattr(stay, "guests") and stay.guests:
                            return stay.guests[0].full_name
        except Exception:
            pass
        return "Vacía"

# 5. CLASE STAY (Se define al final porque usa Guest y Room)
class Stay(Base):
    __tablename__ = "stays"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('rooms.id'))
    check_in = Column(DateTime, default=datetime.now)
    check_out = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # Relaciones
    room = relationship("Room", back_populates="active_stays")
    guests = relationship("Guest", secondary=stay_guests)

# 6. OTRAS CLASES
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(128))
    full_name = Column(String(100))
    email = Column(String(100))
    role = Column(Enum(UserRole), default=UserRole.RECEPCIONIST)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

class Configuration(Base):
    __tablename__ = "configurations"
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True)
    value = Column(String(500))
    description = Column(String(200))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)