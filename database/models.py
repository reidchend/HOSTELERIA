from sqlalchemy import Column, Integer, String, Float, Enum, Boolean, DateTime, Date, ForeignKey, Table
from sqlalchemy.orm import relationship
from database.connection import Base
import enum
from datetime import datetime

# --- 1. ENUMS ---
class UserRole(enum.Enum):
    ADMIN = "admin"
    RECEPCIONIST = "receptionist"

class RoomStatus(enum.Enum):
    FREE = "free"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    CLEANING = "cleaning"
    MAINTENANCE = "maintenance"

class PaymentMethod(enum.Enum):
    CASH_USD = "Efectivo $"
    CASH_BS = "Efectivo Bs"
    TRANSFER_BS = "Transferencia Bs"
    PAGO_MOVIL = "Pago Móvil"
    ZELLE = "Zelle"
    DEBIT_CARD = "Tarjeta Débito"

# --- 2. TABLAS INTERMEDIAS ---
stay_guests = Table(
    'stay_guests',
    Base.metadata,
    Column('stay_id', Integer, ForeignKey('stays.id')),
    Column('guest_id', Integer, ForeignKey('guests.id'))
)

# --- 3. MODELOS ---

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

    active_stays = relationship("Stay", back_populates="room", lazy="selectin")

    @property
    def current_guest_name(self):
        try:
            if self.active_stays:
                for stay in self.active_stays:
                    if stay.is_active and stay.guests:
                        return stay.guests[0].full_name
        except: pass
        return "Vacía"

class Stay(Base):
    __tablename__ = "stays"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('rooms.id'))
    check_in = Column(DateTime, default=datetime.now)
    check_out = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # --- LOGICA FINANCIERA DEL FOLIO ---
    # Saldo acumulado a favor del cliente para consumos
    deposit_balance_usd = Column(Float, default=0.0) 
    
    # Relaciones
    room = relationship("Room", back_populates="active_stays")
    guests = relationship("Guest", secondary=stay_guests, lazy="selectin")
    payments = relationship("Payment", back_populates="stay", lazy="selectin")
    extra_charges = relationship("ExtraCharge", back_populates="stay", lazy="selectin")

class Payment(Base):
    """Registro de entradas de dinero (Abonos)"""
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    stay_id = Column(Integer, ForeignKey('stays.id'))
    
    amount_usd = Column(Float, default=0.0)
    amount_bs = Column(Float, default=0.0)
    exchange_rate = Column(Float) # Tasa usada en el momento
    method = Column(Enum(PaymentMethod))
    reference = Column(String(100)) # Num. de transferencia o confirmación
    description = Column(String(200)) # Ej: "Abono inicial", "Pago noche extra"
    
    # Si es True, el dinero salió de caja (Vuelto)
    is_refund = Column(Boolean, default=False) 
    created_at = Column(DateTime, default=datetime.now)

    stay = relationship("Stay", back_populates="payments")

class ExtraCharge(Base):
    """Consumos adicionales (Restaurante, Lavandería, etc)"""
    __tablename__ = "extra_charges"
    id = Column(Integer, primary_key=True)
    stay_id = Column(Integer, ForeignKey('stays.id'))
    service_name = Column(String(100))
    amount_usd = Column(Float)
    quantity = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)

    stay = relationship("Stay", back_populates="extra_charges")

class CashDrawer(Base):
    __tablename__ = "cash_drawer"
    id = Column(Integer, primary_key=True)
    # Caja Principal (Ventas del turno)
    main_balance_usd = Column(Float, default=0.0)
    main_balance_bs = Column(Float, default=0.0)
    
    # Caja Chica (Fondo para vueltos)
    petty_cash_usd = Column(Float, default=0.0)
    petty_cash_bs = Column(Float, default=0.0)
    
    last_update = Column(DateTime, default=datetime.now)

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
    key = Column(String(50), unique=True) # Ej: 'dollar_rate'
    value = Column(String(500))
    description = Column(String(200))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Apertura
    start_time = Column(DateTime, default=datetime.now)
    initial_usd = Column(Float, nullable=False)
    initial_bs = Column(Float, nullable=False)
    initial_exchange_rate = Column(Float, nullable=False)
    
    # Cierre
    end_time = Column(DateTime, nullable=True)
    final_usd_expected = Column(Float, nullable=True) # Lo que el sistema cree que hay
    final_bs_expected = Column(Float, nullable=True)
    final_usd_real = Column(Float, nullable=True)     # Lo que el recepcionista contó
    final_bs_real = Column(Float, nullable=True)
    
    is_active = Column(Boolean, default=True)
    
    user = relationship("User")