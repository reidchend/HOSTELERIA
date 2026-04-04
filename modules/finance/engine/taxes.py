# modules/finance/engine/taxes.py
"""
Motor de cálculo de impuestos.
Trabaja exclusivamente con Decimal para garantizar precisión exacta.

Los precios se guardan como PRECIO FINAL (con IVA incluido).
El sistema extrae el IVA internamente.
"""
from utils.decimal_utils import Decimal, ROUND_HALF_UP, D

_CENT = Decimal("0.01")


def calcular_iva(subtotal: Decimal, porcentaje: Decimal) -> Decimal:
    """
    Devuelve el monto de IVA sobre el subtotal dado.
    Redondeo HALF_UP a 4 decimales (se redondea a 2 al presentar).
    """
    return (subtotal * porcentaje / D("100")).quantize(
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
    
    El precio_unitario es el PRECIO FINAL (con IVA incluido).
    Se extrae el subtotal (base sin IVA) y el IVA.

    Devuelve:
        (subtotal, iva, total)  ← todos Decimal, redondeados a 2 cifras
    
    El total siempre es igual al precio final configurado × cantidad.
    El IVA se extrae del total: iva = total - (total / (1 + iva%))
    """
    total_exacto = precio_unitario * cantidad
    total = total_exacto.quantize(_CENT, rounding=ROUND_HALF_UP)

    if aplica_iva and porcentaje_iva > 0:
        # Extraer el IVA del precio final (que ya lo incluye)
        # subtotal = total / (1 + iva/100)
        factor = D("1") + porcentaje_iva / D("100")
        subtotal = (total / factor).quantize(_CENT, rounding=ROUND_HALF_UP)
        iva = total - subtotal  # diferencia exacta
    else:
        iva   = D("0")
        subtotal = total

    return subtotal, iva, total
