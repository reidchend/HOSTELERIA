# database/models.py — v2: motor de libro contable (ledger)
#
# CAMBIOS vs v1:
#   • Float → Numeric(12,4) → Python recibe Decimal, sin errores de punto flotante.
#   • CargoExtra, LineaCuenta, TipoLinea, TransaccionCobro → ELIMINADOS.
#   • FolioLinea: tabla única para todos los cargos (hospedaje, extras, deudas).
#     Tiene precio_unitario, IVA por línea y total calculado con Decimal.
#   • LedgerMovimiento: libro contable.  saldo = SUM(debe) − SUM(haber).
#   • Estadia.deposito_usd eliminado.

from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean,
    DateTime, Date, Enum, ForeignKey, Table,
)
from sqlalchemy.orm import relationship
from database.connection import Base
import enum
from datetime import datetime


# ══════════════════════════════════════════════════════════════════════════════
# ENUMERACIONES
# ══════════════════════════════════════════════════════════════════════════════

class RolUsuario(enum.Enum):
    ADMIN        = "admin"
    RECEPCIONIST = "receptionist"


class EstadoHabitacion(enum.Enum):
    FREE        = "free"
    OCCUPIED    = "occupied"
    RESERVED    = "reserved"
    CLEANING    = "cleaning"
    MAINTENANCE = "maintenance"


class MetodoPago(enum.Enum):
    CASH_USD    = "Efectivo $"
    CASH_BS     = "Efectivo Bs"
    TRANSFER_BS = "Transferencia Bs"
    PAGO_MOVIL  = "Pago Móvil"
    ZELLE       = "Zelle"
    DEBIT_CARD  = "Tarjeta Débito"
    SALDO_FAVOR = "Saldo a Favor"


class TipoLinea(enum.Enum):
    HOSPEDAJE       = "hospedaje"
    CARGO_EXTRA     = "cargo_extra"
    SALDO_PENDIENTE = "saldo_pendiente"


class TipoMovimiento(enum.Enum):
    CARGO      = "cargo"        # aumenta la deuda (debe↑)
    PAGO       = "pago"         # reduce la deuda (haber↑)
    DEVOLUCION = "devolucion"   # dinero sale de caja al huésped (haber↑)
    AJUSTE     = "ajuste"       # corrección manual


# ══════════════════════════════════════════════════════════════════════════════
# TABLA INTERMEDIA
# ══════════════════════════════════════════════════════════════════════════════

estadia_huespedes = Table(
    'stay_guests', Base.metadata,
    Column('stay_id',  Integer, ForeignKey('stays.id')),
    Column('guest_id', Integer, ForeignKey('guests.id')),
)


# ══════════════════════════════════════════════════════════════════════════════
# MODELOS
# ══════════════════════════════════════════════════════════════════════════════

class TipoHabitacion(Base):
    """
    Catálogo de tipos de habitación con su precio base.
    Cuando una habitación cambia de tipo, hereda automáticamente
    precio_base_usd y precio_actual_usd de esta tabla.
    """
    __tablename__ = "room_types"

    id                = Column(Integer, primary_key=True)
    nombre            = Column(String(50), unique=True, nullable=False)
    precio_base_usd   = Column(Numeric(12, 4), nullable=False, default=0)
    precio_actual_usd = Column(Numeric(12, 4), nullable=False, default=0)
    capacidad_default = Column(Integer, default=2)
    descripcion       = Column(String(200), nullable=True)


class Huesped(Base):
    __tablename__ = "guests"

    id               = Column(Integer, primary_key=True)
    documento        = Column(String(20), unique=True, index=True)
    nombre           = Column(String(50))
    apellido         = Column(String(50))
    fecha_nacimiento = Column(Date, nullable=True)
    nacionalidad     = Column(String(50))
    profesion        = Column(String(50))
    telefono         = Column(String(20))
    vehiculo         = Column(String(100), nullable=True)
    credito_usd      = Column(Numeric(12, 4), default=0)
    lista_negra      = Column(Boolean, default=False)
    motivo_veto      = Column(String(300), nullable=True)

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"


class Habitacion(Base):
    __tablename__ = "rooms"

    id                = Column(Integer, primary_key=True)
    numero            = Column(String(10), unique=True, index=True)
    piso              = Column(Integer)
    tipo              = Column(String(50))
    estado            = Column(Enum(EstadoHabitacion), default=EstadoHabitacion.FREE)
    precio_base_usd   = Column(Numeric(12, 4))
    precio_actual_usd = Column(Numeric(12, 4))
    capacidad_maxima  = Column(Integer, default=2)
    descripcion       = Column(String(200))
    amenidades        = Column(String(200))
    ultima_limpieza   = Column(DateTime, default=datetime.now)

    estadias_activas = relationship("Estadia", back_populates="habitacion", lazy="selectin")

    @property
    def nombre_huesped_actual(self):
        try:
            for e in self.estadias_activas:
                if e.activa and e.huespedes:
                    return e.huespedes[0].nombre_completo
        except Exception:
            pass
        return "Vacía"


class Estadia(Base):
    __tablename__ = "stays"

    id            = Column(Integer, primary_key=True)
    habitacion_id = Column(Integer, ForeignKey('rooms.id'))
    entrada       = Column(DateTime, default=datetime.now)
    salida        = Column(DateTime, nullable=True)
    activa        = Column(Boolean, default=True)
    notas         = Column(String(1000), nullable=True)

    habitacion         = relationship("Habitacion", back_populates="estadias_activas")
    huespedes          = relationship("Huesped", secondary=estadia_huespedes, lazy="selectin")
    pagos              = relationship("Pago",              back_populates="estadia", lazy="selectin")
    folio_lineas       = relationship("FolioLinea",        back_populates="estadia", lazy="selectin")
    ledger_movimientos = relationship("LedgerMovimiento",  back_populates="estadia", lazy="selectin")


class FolioLinea(Base):
    """
    Un cargo en el folio de la estadía.
    Reemplaza LineaCuenta + CargoExtra.

    precio_unitario_usd  precio/unidad SIN IVA
    subtotal_usd         cant × precio_unitario
    iva_usd              impuesto sobre el subtotal
    total_usd            subtotal + iva  (lo que se cobra)
    cancelada            True = ya cobrada
    """
    __tablename__ = "folio_lines"

    id                  = Column(Integer, primary_key=True)
    estadia_id          = Column(Integer, ForeignKey("stays.id"), nullable=False)
    tipo                = Column(Enum(TipoLinea), nullable=False)
    concepto            = Column(String(200), nullable=False)
    cantidad            = Column(Numeric(10, 2), default=1)
    precio_unitario_usd = Column(Numeric(12, 4), nullable=False)
    aplica_iva          = Column(Boolean, default=False)
    porcentaje_iva      = Column(Numeric(5, 2), default=0)
    subtotal_usd        = Column(Numeric(12, 4), nullable=False)
    iva_usd             = Column(Numeric(12, 4), default=0)
    total_usd           = Column(Numeric(12, 4), nullable=False)
    cancelada           = Column(Boolean, default=False)
    creado_en           = Column(DateTime, default=datetime.now)

    estadia = relationship("Estadia", back_populates="folio_lineas")


class LedgerMovimiento(Base):
    """
    Asiento del libro contable.
    debe_usd  → dinero que el huésped debe (cargo).
    haber_usd → dinero recibido o devuelto.
    saldo de la estadía = SUM(debe_usd) - SUM(haber_usd)
    """
    __tablename__ = "ledger"

    id             = Column(Integer, primary_key=True)
    estadia_id     = Column(Integer, ForeignKey("stays.id"), nullable=False)
    tipo           = Column(Enum(TipoMovimiento), nullable=False)
    concepto       = Column(String(200), nullable=False)
    debe_usd       = Column(Numeric(12, 4), default=0)
    haber_usd      = Column(Numeric(12, 4), default=0)
    tasa_cambio    = Column(Numeric(12, 4), nullable=False)
    referencia     = Column(String(100), default="")
    folio_linea_id = Column(Integer, ForeignKey("folio_lines.id"), nullable=True)
    pago_id        = Column(Integer, ForeignKey("payments.id"),    nullable=True)
    creado_en      = Column(DateTime, default=datetime.now)

    estadia     = relationship("Estadia",      back_populates="ledger_movimientos")
    folio_linea = relationship("FolioLinea")
    pago        = relationship("Pago")


class Pago(Base):
    """
    Transacción de dinero (ingreso o devolución).
    es_devolucion=True → dinero sale de caja al huésped (vuelto).
    Cada Pago genera un LedgerMovimiento vía ledger.registrar_desde_pago().
    """
    __tablename__ = "payments"

    id            = Column(Integer, primary_key=True)
    estadia_id    = Column(Integer, ForeignKey('stays.id'))
    monto_usd     = Column(Numeric(12, 4), default=0)
    monto_bs      = Column(Numeric(12, 4), default=0)
    tasa_cambio   = Column(Numeric(12, 4))
    metodo        = Column(Enum(MetodoPago))
    referencia    = Column(String(100))
    descripcion   = Column(String(200))
    es_devolucion = Column(Boolean, default=False)
    creado_en     = Column(DateTime, default=datetime.now)

    estadia = relationship("Estadia", back_populates="pagos")


class Caja(Base):
    __tablename__ = "cash_drawer"

    id                   = Column(Integer, primary_key=True)
    saldo_principal_usd  = Column(Numeric(12, 4), default=0)
    saldo_principal_bs   = Column(Numeric(12, 4), default=0)
    caja_chica_usd       = Column(Numeric(12, 4), default=0)
    caja_chica_bs        = Column(Numeric(12, 4), default=0)
    ultima_actualizacion = Column(DateTime, default=datetime.now)


class Usuario(Base):
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
    __tablename__ = "configurations"

    id             = Column(Integer, primary_key=True)
    clave          = Column(String(50), unique=True)
    valor          = Column(String(500))
    descripcion    = Column(String(200))
    actualizado_en = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TipoEvento(enum.Enum):
    """Categoría de un evento en la bitácora del turno."""
    CHECKIN      = "checkin"
    CHECKOUT     = "checkout"
    PAGO         = "pago"
    CARGO_EXTRA  = "cargo_extra"
    VUELTO       = "vuelto"
    RENOVACION   = "renovacion"
    RESERVACION  = "reservacion"
    CAJA         = "caja"           # apertura, cierre, aporte
    NOTA         = "nota"           # mensaje libre del recepcionista
    SISTEMA      = "sistema"        # eventos internos


class BitacoraEvento(Base):
    """
    Registro cronológico de todo lo que ocurre durante un turno.
    Equivale al chat de WhatsApp pero dentro del sistema.

    turno_id       → turno al que pertenece el evento
    tipo           → categoría (CHECKIN, PAGO, VUELTO, etc.)
    habitacion     → número de habitación (ej: "26" o "5/6" para múltiples)
    concepto       → descripción legible del evento
    monto_usd      → monto en USD (0 si no aplica)
    monto_bs       → monto en Bs  (0 si no aplica)
    metodo_pago    → método si fue un cobro/vuelto
    referencia     → nro. de confirmación / ref de transferencia
    recepcionista  → nombre de quien registró el evento
    confirmado     → True = confirmado, False = pendiente de confirmar
    """
    __tablename__ = "bitacora"

    id             = Column(Integer, primary_key=True)
    turno_id       = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    tipo           = Column(Enum(TipoEvento), nullable=False)
    habitacion     = Column(String(20),  default="")
    concepto       = Column(String(400), nullable=False)
    monto_usd      = Column(Numeric(12, 4), default=0)
    monto_bs       = Column(Numeric(12, 4), default=0)
    metodo_pago    = Column(String(50),  default="")
    referencia     = Column(String(100), default="")
    recepcionista  = Column(String(100), default="")
    confirmado     = Column(Boolean, default=True)
    creado_en      = Column(DateTime, default=datetime.now)

    turno = relationship("Turno", back_populates="eventos")


class Turno(Base):
    __tablename__ = "shifts"

    id           = Column(Integer, primary_key=True)
    usuario_id   = Column(Integer, ForeignKey("users.id"))
    hora_inicio  = Column(DateTime, default=datetime.now)
    inicial_usd  = Column(Numeric(12, 4), nullable=False)
    inicial_bs   = Column(Numeric(12, 4), nullable=False)
    tasa_inicial = Column(Numeric(12, 4), nullable=False)
    hora_fin     = Column(DateTime, nullable=True)
    usd_esperado = Column(Numeric(12, 4), nullable=True)
    bs_esperado  = Column(Numeric(12, 4), nullable=True)
    usd_real     = Column(Numeric(12, 4), nullable=True)
    bs_real      = Column(Numeric(12, 4), nullable=True)
    activo       = Column(Boolean, default=True)

    usuario  = relationship("Usuario")
    eventos  = relationship("BitacoraEvento", back_populates="turno",
                             order_by="BitacoraEvento.creado_en", lazy="dynamic")