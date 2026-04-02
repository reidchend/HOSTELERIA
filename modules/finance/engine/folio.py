# modules/finance/engine/folio.py
"""
Motor de folio (cargos de la estadía).

Centraliza la creación de FolioLinea y garantiza que cada cargo
quede registrado también en el ledger como asiento CARGO.

REGLAS DE IVA:
  - Hospedaje:   precio_unitario es el precio/noche BASE (sin IVA).
                 El motor calcula y aplica el IVA configurado.
  - Cargo extra: el recepcionista ingresa el monto final YA con IVA.
                 aplica_iva=False; el monto se guarda tal cual.
  - Saldo pendiente: monto plano, sin IVA.
"""
from utils.decimal_utils import Decimal, D
from utils.db import sesion
from datetime import datetime
from database.models import FolioLinea, TipoLinea
from modules.finance.engine import taxes, ledger as led


# ── Creación de líneas ────────────────────────────────────────────────────────

def crear_linea_hospedaje(
    sesion,
    estadia_id: int,
    habitacion_numero: str,
    noches: int,
    precio_noche_usd: Decimal,
    config,                        # ConfigFinanciera
    concepto_extra: str = "",
    aplica_iva: bool = True,
) -> FolioLinea:
    """
    Crea una FolioLinea de hospedaje y su asiento CARGO en el ledger.
    El precio_noche_usd es el precio BASE sin IVA.
    
    Para habitaciones operativas (por hora), usar aplica_iva=False
    ya que el precio de $20/hora ya incluye todo.
    """
    porcentaje_iva = D(str(config.porcentaje_iva))
    precio_u       = D(str(precio_noche_usd))
    cantidad       = D(str(noches))
    tasa           = D(str(config.tasa_cambio))

    subtotal, iva, total = taxes.desglosar_precio(
        precio_u, cantidad, porcentaje_iva, aplica_iva=aplica_iva
    )

    concepto = (
        concepto_extra
        if concepto_extra
        else f"Hospedaje — Hab. {habitacion_numero} "
             f"({noches} noche{'s' if noches != 1 else ''})"
    )

    linea = FolioLinea(
        estadia_id          = estadia_id,
        tipo                = TipoLinea.HOSPEDAJE,
        concepto            = concepto,
        cantidad            = cantidad,
        precio_unitario_usd = precio_u,
        aplica_iva          = True,
        porcentaje_iva      = porcentaje_iva,
        subtotal_usd        = subtotal,
        iva_usd             = iva,
        total_usd           = total,
        cancelada           = False,
        creado_en           = datetime.now(),
    )
    sesion.add(linea)
    sesion.flush()   # obtener ID para el ledger

    led.registrar_cargo(
        sesion,
        estadia_id     = estadia_id,
        concepto       = concepto,
        monto_usd      = total,
        tasa           = tasa,
        folio_linea_id = linea.id,
    )
    return linea


def crear_cargo_extra(
    sesion,
    estadia_id: int,
    concepto: str,
    cantidad: int,
    precio_unitario_usd: Decimal,
    config,
) -> FolioLinea:
    """
    Crea una FolioLinea de cargo extra (sin IVA adicional — el monto
    ingresado por el recepcionista ya lo incluye).
    """
    tasa     = D(str(config.tasa_cambio))
    precio_u = D(str(precio_unitario_usd))
    cant     = D(str(cantidad))

    subtotal, iva, total = taxes.desglosar_precio(
        precio_u, cant, D("0"), aplica_iva=False
    )

    concepto_completo = (
        f"{concepto} x{cantidad}" if cantidad > 1 else concepto
    )

    linea = FolioLinea(
        estadia_id          = estadia_id,
        tipo                = TipoLinea.CARGO_EXTRA,
        concepto            = concepto_completo,
        cantidad            = cant,
        precio_unitario_usd = precio_u,
        aplica_iva          = False,
        porcentaje_iva      = D("0"),
        subtotal_usd        = subtotal,
        iva_usd             = iva,
        total_usd           = total,
        cancelada           = False,
        creado_en           = datetime.now(),
    )
    sesion.add(linea)
    sesion.flush()

    led.registrar_cargo(
        sesion,
        estadia_id     = estadia_id,
        concepto       = concepto_completo,
        monto_usd      = total,
        tasa           = tasa,
        folio_linea_id = linea.id,
    )
    return linea


def crear_saldo_pendiente(
    sesion,
    estadia_id: int,
    monto_usd: Decimal,
    concepto: str,
    config,
) -> FolioLinea:
    """
    Crea una línea de saldo pendiente (deuda de estadías anteriores
    o cobro parcial no saldado).
    """
    tasa  = D(str(config.tasa_cambio))
    monto = D(str(monto_usd))

    linea = FolioLinea(
        estadia_id          = estadia_id,
        tipo                = TipoLinea.SALDO_PENDIENTE,
        concepto            = concepto,
        cantidad            = D("1"),
        precio_unitario_usd = monto,
        aplica_iva          = False,
        porcentaje_iva      = D("0"),
        subtotal_usd        = monto,
        iva_usd             = D("0"),
        total_usd           = monto,
        cancelada           = False,
        creado_en           = datetime.now(),
    )
    sesion.add(linea)
    sesion.flush()

    led.registrar_cargo(
        sesion,
        estadia_id     = estadia_id,
        concepto       = concepto,
        monto_usd      = monto,
        tasa           = tasa,
        folio_linea_id = linea.id,
    )
    return linea


# ── Consultas ─────────────────────────────────────────────────────────────────

def lineas_pendientes(sesion, estadia_id: int) -> list:
    """Devuelve las FolioLinea sin cobrar, ordenadas por fecha."""
    return (
        sesion.query(FolioLinea)
        .filter(
            FolioLinea.estadia_id == estadia_id,
            FolioLinea.cancelada  == False,
        )
        .order_by(FolioLinea.creado_en)
        .all()
    )


def cancelar_lineas(sesion, linea_ids: list) -> None:
    """Marca como canceladas las líneas indicadas."""
    for lid in linea_ids:
        linea = sesion.get(FolioLinea, lid)
        if linea:
            linea.cancelada = True


def total_folio(sesion, estadia_id: int) -> Decimal:
    """Suma el total_usd de todas las líneas (canceladas o no)."""
    from sqlalchemy import func
    res = sesion.query(func.sum(FolioLinea.total_usd)).filter(
        FolioLinea.estadia_id == estadia_id
    ).scalar()
    return D(str(res or 0))


def total_pendiente(sesion, estadia_id: int) -> Decimal:
    """Suma el total_usd de las líneas aún no cobradas."""
    from sqlalchemy import func
    res = sesion.query(func.sum(FolioLinea.total_usd)).filter(
        FolioLinea.estadia_id == estadia_id,
        FolioLinea.cancelada  == False,
    ).scalar()
    return D(str(res or 0))