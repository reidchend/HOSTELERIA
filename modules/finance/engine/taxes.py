# modules/finance/engine/taxes.py
"""
Motor de cálculo de impuestos.
Trabaja exclusivamente con Decimal para garantizar precisión exacta.
"""
from decimal import Decimal, ROUND_HALF_UP

_CENT = Decimal("0.01")
_D    = lambda x: Decimal(str(x))


def calcular_iva(subtotal: Decimal, porcentaje: Decimal) -> Decimal:
    """
    Devuelve el monto de IVA sobre el subtotal dado.
    Redondeo HALF_UP a 4 decimales (se redondea a 2 al presentar).
    """
    return (subtotal * porcentaje / _D("100")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def desglosar_precio(
    precio_unitario: Decimal,
    cantidad: Decimal,
    porcentaje_iva: Decimal,
    aplica_iva: bool,
) -> tuple:
    """
    Calcula los componentes de una línea del folio.

    Devuelve:
        (subtotal, iva, total)  ← todos Decimal, redondeados a 2 cifras

    El subtotal se redondea primero; el IVA es la diferencia técnica
    para que subtotal + iva == total exactamente (sin centavos perdidos).
    """
    subtotal_exacto = precio_unitario * cantidad
    subtotal = subtotal_exacto.quantize(_CENT, rounding=ROUND_HALF_UP)

    if aplica_iva and porcentaje_iva > 0:
        total_exacto = subtotal_exacto * (_D("1") + porcentaje_iva / _D("100"))
        total = total_exacto.quantize(_CENT, rounding=ROUND_HALF_UP)
        iva   = total - subtotal          # diferencia exacta, sin error de redondeo
    else:
        iva   = _D("0")
        total = subtotal

    return subtotal, iva, total