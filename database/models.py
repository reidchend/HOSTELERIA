# database/models.py

from sqlalchemy import Column, Integer, String, Float, Enum, Boolean, DateTime, Date, ForeignKey, Table
from sqlalchemy.orm import relationship
from database.connection import Base
import enum
from datetime import datetime


# ══════════════════════════════════════════════════════════════════
# ENUMERACIONES
# ══════════════════════════════════════════════════════════════════

class RolUsuario(enum.Enum):
    """Roles disponibles para los usuarios del sistema."""
    ADMIN        = "admin"
    RECEPCIONIST = "receptionist"


class EstadoHabitacion(enum.Enum):
    """Estados posibles de una habitación en el mapa."""
    FREE        = "free"
    OCCUPIED    = "occupied"
    RESERVED    = "reserved"
    CLEANING    = "cleaning"
    MAINTENANCE = "maintenance"


class MetodoPago(enum.Enum):
    """Métodos de pago aceptados en el punto de cobro."""
    CASH_USD     = "Efectivo $"
    CASH_BS      = "Efectivo Bs"
    TRANSFER_BS  = "Transferencia Bs"
    PAGO_MOVIL   = "Pago Móvil"
    ZELLE        = "Zelle"
    DEBIT_CARD   = "Tarjeta Débito"
    SALDO_FAVOR  = "Saldo a Favor"          # Crédito acumulado del huésped


# ══════════════════════════════════════════════════════════════════
# TABLA INTERMEDIA  Estadia ↔ Huesped  (relación muchos a muchos)
# ══════════════════════════════════════════════════════════════════

estadia_huespedes = Table(
    'stay_guests',          # nombre de la tabla en la BD (no cambia para compatibilidad)
    Base.metadata,
    Column('stay_id',  Integer, ForeignKey('stays.id')),
    Column('guest_id', Integer, ForeignKey('guests.id'))
)


# ══════════════════════════════════════════════════════════════════
# MODELOS
# ══════════════════════════════════════════════════════════════════

class Huesped(Base):
    """
    Persona registrada en el sistema.
    El campo credito_usd persiste entre estadías y se usa para
    acreditar sobrantes de pagos a futuras visitas.
    """
    __tablename__ = "guests"

    id               = Column(Integer, primary_key=True)
    documento        = Column(String(20), unique=True, index=True)   # Cédula / pasaporte
    nombre           = Column(String(50))
    apellido         = Column(String(50))
    fecha_nacimiento = Column(Date, nullable=True)
    nacionalidad     = Column(String(50))
    profesion        = Column(String(50))
    telefono         = Column(String(20))
    vehiculo         = Column(String(100), nullable=True)            # Placa / marca del vehículo
    credito_usd      = Column(Float, default=0.0)                    # Saldo a favor entre estadías
    lista_negra      = Column(Boolean, default=False)               # Huésped vetado
    motivo_veto      = Column(String(300), nullable=True)           # Razón del veto

    @property
    def nombre_completo(self):
        """Devuelve el nombre y apellido unidos, útil para mostrar en pantalla."""
        return f"{self.nombre} {self.apellido}"


class Habitacion(Base):
    """
    Habitación física del hotel con sus precios y estado actual.
    La relación estadias_activas permite saber quién está hospedado.
    """
    __tablename__ = "rooms"

    id               = Column(Integer, primary_key=True)
    numero           = Column(String(10), unique=True, index=True)
    piso             = Column(Integer)
    tipo             = Column(String(50))
    estado           = Column(Enum(EstadoHabitacion), default=EstadoHabitacion.FREE)
    precio_base_usd  = Column(Float)                                 # Precio de lista
    precio_actual_usd= Column(Float)                                 # Precio aplicado (puede tener descuento)
    capacidad_maxima = Column(Integer, default=2)
    descripcion      = Column(String(200))
    amenidades       = Column(String(200))
    ultima_limpieza  = Column(DateTime, default=datetime.now)

    # Una habitación puede tener varias estadías (historial + actual)
    estadias_activas = relationship("Estadia", back_populates="habitacion", lazy="selectin")

    @property
    def nombre_huesped_actual(self):
        """
        Devuelve el nombre del huésped registrado en la estadía activa.
        Retorna 'Vacía' si la habitación está libre.
        """
        try:
            if self.estadias_activas:
                for estadia in self.estadias_activas:
                    if estadia.activa and estadia.huespedes:
                        return estadia.huespedes[0].nombre_completo
        except Exception:
            pass
        return "Vacía"


class Estadia(Base):
    """
    Registro de una ocupación: une una habitación con sus huéspedes.
    deposito_usd acumula saldo a favor dentro de la estadía actual.
    """
    __tablename__ = "stays"

    id            = Column(Integer, primary_key=True)
    habitacion_id = Column(Integer, ForeignKey('rooms.id'))
    entrada       = Column(DateTime, default=datetime.now)           # Check-in real
    salida        = Column(DateTime, nullable=True)                  # Check-out estimado
    activa        = Column(Boolean, default=True)
    deposito_usd  = Column(Float, default=0.0)                       # Adelantos / saldo en la estadía
    notas         = Column(String(1000), nullable=True)              # Observaciones de la estadía

    # Relaciones
    habitacion    = relationship("Habitacion", back_populates="estadias_activas")
    huespedes     = relationship("Huesped", secondary=estadia_huespedes, lazy="selectin")
    pagos         = relationship("Pago", back_populates="estadia", lazy="selectin")
    cargos_extras = relationship("CargoExtra", back_populates="estadia", lazy="selectin")
    lineas_cuenta = relationship("LineaCuenta",        back_populates="estadia", lazy="selectin")
    transacciones = relationship("TransaccionCobro",   back_populates="estadia", lazy="selectin")


class Pago(Base):
    """
    Registro de un ingreso de dinero (abono a la cuenta del huésped).
    Si es_devolucion=True, el dinero SALE de caja (vuelto entregado).
    """
    __tablename__ = "payments"

    id            = Column(Integer, primary_key=True)
    estadia_id    = Column(Integer, ForeignKey('stays.id'))
    monto_usd     = Column(Float, default=0.0)
    monto_bs      = Column(Float, default=0.0)
    tasa_cambio   = Column(Float)                                    # Tasa vigente en el momento del cobro
    metodo        = Column(Enum(MetodoPago))
    referencia    = Column(String(100))                              # Nro. de transferencia / confirmación
    descripcion   = Column(String(200))
    es_devolucion = Column(Boolean, default=False)                   # True = salida de caja (vuelto)
    creado_en     = Column(DateTime, default=datetime.now)

    estadia         = relationship("Estadia", back_populates="pagos")


class CargoExtra(Base):
    """
    Consumo adicional cargado a la cuenta: restaurante, lavandería, etc.
    """
    __tablename__ = "extra_charges"

    id             = Column(Integer, primary_key=True)
    estadia_id     = Column(Integer, ForeignKey('stays.id'))
    nombre_servicio= Column(String(100))
    monto_usd      = Column(Float)
    cantidad       = Column(Integer, default=1)
    creado_en      = Column(DateTime, default=datetime.now)

    estadia = relationship("Estadia", back_populates="cargos_extras")


class Caja(Base):
    """
    Registro único de los saldos físicos de la caja.
    saldo_principal_* → dinero de ventas del turno.
    caja_chica_*      → fondo fijo para dar vueltos.
    """
    __tablename__ = "cash_drawer"

    id                  = Column(Integer, primary_key=True)
    saldo_principal_usd = Column(Float, default=0.0)
    saldo_principal_bs  = Column(Float, default=0.0)
    caja_chica_usd      = Column(Float, default=0.0)
    caja_chica_bs       = Column(Float, default=0.0)
    ultima_actualizacion= Column(DateTime, default=datetime.now)


class Usuario(Base):
    """Cuenta de acceso al sistema (admin o recepcionista)."""
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True)
    nombre_usuario  = Column(String(50), unique=True, index=True)
    hash_contrasena = Column(String(128))
    nombre_completo = Column(String(100))
    correo          = Column(String(100))
    rol             = Column(Enum(RolUsuario), default=RolUsuario.RECEPCIONIST)
    activo          = Column(Boolean, default=True)
    creado_en       = Column(DateTime, default=datetime.now)


class Configuracion(Base):
    """
    Parámetros editables del sistema almacenados como clave-valor.
    Ejemplos: tasa de cambio, nombre del hotel, porcentaje de IVA.
    """
    __tablename__ = "configurations"

    id           = Column(Integer, primary_key=True)
    clave        = Column(String(50), unique=True)
    valor        = Column(String(500))
    descripcion  = Column(String(200))
    actualizado_en = Column(DateTime, default=datetime.now, onupdate=datetime.now)



class TipoLinea(enum.Enum):
    """Origen de una línea de cuenta abierta."""
    HOSPEDAJE      = "hospedaje"
    CARGO_EXTRA    = "cargo_extra"
    SALDO_PENDIENTE = "saldo_pendiente"  # Deuda parcial de una transacción


class TransaccionCobro(Base):
    """
    Agrupa un evento de cobro: qué líneas se seleccionaron, cuánto se pagó
    y si quedó saldo pendiente.
    Permite mostrar el historial de facturas agrupado en details.py.
    """
    __tablename__ = "cobro_transactions"

    id             = Column(Integer, primary_key=True)
    estadia_id     = Column(Integer, ForeignKey("stays.id"), nullable=False)
    total_seleccionado = Column(Float, nullable=False)         # Lo que se intentó cobrar
    total_pagado   = Column(Float, nullable=False)             # Lo que realmente ingresó
    saldo_pendiente = Column(Float, default=0.0)               # Diferencia (0 si completo)
    creado_en      = Column(DateTime, default=datetime.now)

    estadia = relationship("Estadia", back_populates="transacciones")
    lineas  = relationship("LineaCuenta", back_populates="transaccion")


class LineaCuenta(Base):
    """
    Línea de cuenta abierta de una estadía.
    Cada cargo (hospedaje, servicio extra, renovación) genera una línea.

    cancelada=True      → ya fue cobrada (total o parcialmente).
    transaccion_id      → agrupa la línea bajo un cobro específico.
    """
    __tablename__ = "account_lines"

    id               = Column(Integer, primary_key=True)
    estadia_id       = Column(Integer, ForeignKey("stays.id"), nullable=False)
    transaccion_id   = Column(Integer, ForeignKey("cobro_transactions.id"), nullable=True)
    tipo             = Column(Enum(TipoLinea), nullable=False)
    concepto         = Column(String(200), nullable=False)
    monto_usd        = Column(Float, nullable=False)
    cancelada        = Column(Boolean, default=False)
    creado_en        = Column(DateTime, default=datetime.now)

    estadia     = relationship("Estadia",           back_populates="lineas_cuenta")
    transaccion = relationship("TransaccionCobro",  back_populates="lineas")


class Turno(Base):
    """
    Turno de trabajo de un recepcionista.
    Registra apertura y cierre de caja con los montos físicos contados.
    """
    __tablename__ = "shifts"

    id           = Column(Integer, primary_key=True)
    usuario_id   = Column(Integer, ForeignKey("users.id"))

    # ── Apertura ────────────────────────────────────────────────
    hora_inicio  = Column(DateTime, default=datetime.now)
    inicial_usd  = Column(Float, nullable=False)                     # Efectivo USD al abrir
    inicial_bs   = Column(Float, nullable=False)                     # Efectivo Bs al abrir
    tasa_inicial = Column(Float, nullable=False)                     # Tasa de cambio del día

    # ── Cierre ──────────────────────────────────────────────────
    hora_fin     = Column(DateTime, nullable=True)
    usd_esperado = Column(Float, nullable=True)                      # Lo que el sistema calcula
    bs_esperado  = Column(Float, nullable=True)
    usd_real     = Column(Float, nullable=True)                      # Lo que el recepcionista contó
    bs_real      = Column(Float, nullable=True)

    activo       = Column(Boolean, default=True)

    usuario = relationship("Usuario")