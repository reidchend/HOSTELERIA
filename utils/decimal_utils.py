# utils/decimal_utils.py
"""
Utilidades centralizadas para manejo de Decimal.

Evita la repetición de `_D = lambda x: Decimal(str(x))` en múltiples módulos.
"""

from decimal import Decimal, ROUND_HALF_UP

_D = lambda x: Decimal(str(x))


def D(x) -> Decimal:
    """Convierte cualquier valor a Decimal de forma segura."""
    return _D(x)


def round_decimal(value: Decimal, places: int = 2) -> Decimal:
    """Redondea Decimal al número de decimales especificado."""
    q = Decimal("0.1") ** places
    return value.quantize(q, rounding=ROUND_HALF_UP)


def to_float(value) -> float:
    """Convierte Decimal a float para UI."""
    return float(value)


__all__ = ["Decimal", "ROUND_HALF_UP", "D", "round_decimal", "to_float"]
