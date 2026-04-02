# modules/finance/engine/ledger.py
"""
Libro contable central (Ledger).

Cada operación financiera de la estadía pasa por aquí y genera
un asiento en la tabla `ledger`.

  CARGO      → debe_usd ↑   (el huésped debe más)
  PAGO       → haber_usd ↑  (el huésped abona)
  DEVOLUCION → haber_usd ↑  (se le devuelve dinero al huésped)
  AJUSTE     → puede ser debe o haber

Fórmula:
  saldo = SUM(debe_usd) - SUM(haber_usd)
  > 0  → el huésped aún debe
  ≈ 0  → saldado
  < 0  → a favor del huésped (sobrante)
"""
from utils.decimal_utils import Decimal, D
from utils.db import sesion
from datetime import datetime
from sqlalchemy import func
from database.models import LedgerMovimiento, TipoMovimiento


# ── Escritura ────────────────────────────────────────────────────────────────

def registrar_cargo(
    sesion,
    estadia_id: int,
    concepto: str,
    monto_usd: Decimal,
    tasa: Decimal,
    referencia: str = "",
    folio_linea_id: int = None,
) -> LedgerMovimiento:
    """Registra un cargo al folio (huésped debe más)."""
    mov = LedgerMovimiento(
        estadia_id     = estadia_id,
        tipo           = TipoMovimiento.CARGO,
        concepto       = concepto,
        debe_usd       = monto_usd,
        haber_usd      = D("0"),
        tasa_cambio    = tasa,
        referencia     = referencia,
        folio_linea_id = folio_linea_id,
        creado_en      = datetime.now(),
    )
    sesion.add(mov)
    return mov


def registrar_pago(
    sesion,
    estadia_id: int,
    concepto: str,
    monto_usd: Decimal,
    tasa: Decimal,
    referencia: str = "",
    pago_id: int = None,
) -> LedgerMovimiento:
    """Registra un ingreso de dinero (el huésped abona)."""
    mov = LedgerMovimiento(
        estadia_id  = estadia_id,
        tipo        = TipoMovimiento.PAGO,
        concepto    = concepto,
        debe_usd    = D("0"),
        haber_usd   = monto_usd,
        tasa_cambio = tasa,
        referencia  = referencia,
        pago_id     = pago_id,
        creado_en   = datetime.now(),
    )
    sesion.add(mov)
    return mov


def registrar_devolucion(
    sesion,
    estadia_id: int,
    concepto: str,
    monto_usd: Decimal,
    tasa: Decimal,
    referencia: str = "",
    pago_id: int = None,
) -> LedgerMovimiento:
    """Registra una devolución (vuelto que sale de caja al huésped)."""
    mov = LedgerMovimiento(
        estadia_id  = estadia_id,
        tipo        = TipoMovimiento.DEVOLUCION,
        concepto    = concepto,
        debe_usd    = D("0"),
        haber_usd   = monto_usd,   # el haber aumenta → reduce la deuda / o genera crédito
        tasa_cambio = tasa,
        referencia  = referencia,
        pago_id     = pago_id,
        creado_en   = datetime.now(),
    )
    sesion.add(mov)
    return mov


def registrar_ajuste(
    sesion,
    estadia_id: int,
    concepto: str,
    debe_usd: Decimal,
    haber_usd: Decimal,
    tasa: Decimal,
    referencia: str = "",
) -> LedgerMovimiento:
    """Ajuste manual (corrección contable)."""
    mov = LedgerMovimiento(
        estadia_id  = estadia_id,
        tipo        = TipoMovimiento.AJUSTE,
        concepto    = concepto,
        debe_usd    = debe_usd,
        haber_usd   = haber_usd,
        tasa_cambio = tasa,
        referencia  = referencia,
        creado_en   = datetime.now(),
    )
    sesion.add(mov)
    return mov


# ── Consulta ─────────────────────────────────────────────────────────────────

def saldo_estadia(sesion, estadia_id: int) -> Decimal:
    """
    Calcula el saldo de la estadía desde el ledger.
    > 0 → debe   |  ≈ 0 → saldado   |  < 0 → a favor del huésped
    """
    res = sesion.query(
        func.sum(LedgerMovimiento.debe_usd),
        func.sum(LedgerMovimiento.haber_usd),
    ).filter(LedgerMovimiento.estadia_id == estadia_id).first()

    debe  = D(str(res[0] or 0))
    haber = D(str(res[1] or 0))
    return debe - haber


def historial(sesion, estadia_id: int) -> list:
    """Devuelve todos los asientos ordenados del más reciente al más antiguo."""
    return (
        sesion.query(LedgerMovimiento)
        .filter(LedgerMovimiento.estadia_id == estadia_id)
        .order_by(LedgerMovimiento.creado_en.desc())
        .all()
    )