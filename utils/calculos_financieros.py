# utils/calculos_financieros.py
"""
Utilidades financieras de propósito general.

La lógica de negocio (cargos, pagos, saldo) vive en:
  modules/finance/engine/folio.py   → crear cargos, consultar folio
  modules/finance/engine/ledger.py  → libro contable, saldo
  modules/finance/engine/taxes.py   → IVA con Decimal

Este módulo mantiene:
  - leer_config_financiera()  → lee tasa y % IVA de la BD
  - a_bs() / a_usd()         → conversión de moneda
  - ConfigFinanciera          → dataclass compartido
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN FINANCIERA
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConfigFinanciera:
    """
    Parámetros del sistema leídos desde la tabla Configuracion.
    Usa float para compatibilidad con Flet (widgets de texto),
    pero el motor de cálculo (taxes.py) convierte a Decimal internamente.
    """
    tasa_cambio:    float = 1.0
    porcentaje_iva: float = 0.0


def leer_config_financiera(sesion) -> ConfigFinanciera:
    """
    Lee la tasa de cambio y el % de IVA desde la BD.
    Devuelve valores seguros si las claves no existen.
    """
    from database.models import Configuracion

    cfg_tasa = sesion.query(Configuracion).filter(
        Configuracion.clave == "exchange_rate"
    ).first()
    cfg_iva = sesion.query(Configuracion).filter(
        Configuracion.clave == "tax_percentage"
    ).first()

    return ConfigFinanciera(
        tasa_cambio    = float(cfg_tasa.valor) if cfg_tasa else 1.0,
        porcentaje_iva = float(cfg_iva.valor)  if cfg_iva  else 0.0,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSIÓN DE MONEDA
# ══════════════════════════════════════════════════════════════════════════════

def a_bs(monto_usd, tasa) -> float:
    """Convierte USD a Bs. Acepta float o Decimal."""
    return round(float(monto_usd) * float(tasa), 2)


def a_usd(monto_bs, tasa) -> float:
    """Convierte Bs a USD. Protegido contra tasa = 0."""
    t = float(tasa)
    return round(float(monto_bs) / t, 2) if t else 0.0


def a_bs_decimal(monto_usd: Decimal, tasa: Decimal) -> Decimal:
    """Versión Decimal de a_bs para usar dentro de los motores."""
    return (monto_usd * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def a_usd_decimal(monto_bs: Decimal, tasa: Decimal) -> Decimal:
    """Versión Decimal de a_usd."""
    if not tasa:
        return Decimal("0")
    return (monto_bs / tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)