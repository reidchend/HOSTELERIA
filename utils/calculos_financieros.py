# utils/calculos_financieros.py
"""
Módulo centralizado de cálculos financieros del hotel.

Cualquier módulo que necesite saber cuánto debe un huésped, cuánto se ha
pagado o cómo convertir entre monedas debe importar desde aquí en lugar
de repetir la lógica localmente.

Módulos que lo usan actualmente:
  - modules/rooms/details.py          -> para mostrar el estado de cuenta
  - modules/finance/payment_dialog.py -> para calcular folio y saldo en tiempo real

Uso típico:
    from utils.calculos_financieros import leer_config_financiera, calcular_folio, calcular_saldo

    sesion = SesionLocal()
    config = leer_config_financiera(sesion)
    folio  = calcular_folio(estadia, config)
    saldo  = calcular_saldo(folio.total_usd, pagado_bd, pagos_sesion)
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# ESTRUCTURAS DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConfigFinanciera:
    """
    Parámetros del sistema leídos desde la tabla de configuración.
    Obtenida con leer_config_financiera(sesion).
    """
    tasa_cambio:    float = 1.0   # Bolívares por dólar
    porcentaje_iva: float = 0.0   # Porcentaje (ej: 16.0 para 16 %)


@dataclass
class LineaFolio:
    """
    Una línea de la factura: hospedaje o cargo extra.
    total_usd se calcula como cantidad * precio_unitario_usd.
    """
    concepto:            str
    cantidad:            int
    precio_unitario_usd: float

    @property
    def total_usd(self) -> float:
        return self.cantidad * self.precio_unitario_usd


@dataclass
class ResultadoFolio:
    """
    Resultado completo del cálculo de una estadia.
    Centraliza todos los montos para que details.py y payment_dialog.py
    lean exactamente los mismos números sin recalcular.
    """
    lineas:           List[LineaFolio]  # Hospedaje + extras
    subtotal_usd:     float             # Suma bruta sin IVA
    iva_usd:          float             # IVA calculado sobre el subtotal
    total_usd:        float             # subtotal + IVA (lo que se cobra)
    total_bs:         float             # total_usd convertido a Bs
    noches:           int               # Duracion de la estadia en noches
    precio_noche_usd: float             # Precio/noche aplicado
    porcentaje_iva:   float             # % de IVA usado en el calculo
    tasa_cambio:      float             # Tasa usada para convertir a Bs


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES PÚBLICAS
# ══════════════════════════════════════════════════════════════════════════════

def leer_config_financiera(sesion) -> ConfigFinanciera:
    """
    Lee la tasa de cambio y el % de IVA desde la tabla Configuracion.
    Si alguna clave no existe devuelve valores seguros (tasa=1, iva=0).

    Args:
        sesion: Sesion activa de SQLAlchemy.
    """
    from database.models import Configuracion   # import local para evitar ciclos

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


from decimal import Decimal, ROUND_HALF_UP
from typing import List

def calcular_folio(estadia, config: ConfigFinanciera) -> ResultadoFolio:
    _D = lambda x: Decimal(str(x))
    
    habitacion = estadia.habitacion
    # Diferencia de días
    noches = max(1, (estadia.salida.date() - estadia.entrada.date()).days)
    precio_noche = _D(habitacion.precio_actual_usd or habitacion.precio_base_usd)

    lineas: List[LineaFolio] = [
        LineaFolio(
            concepto=f"Hospedaje - Hab. {habitacion.numero} ({noches} noche{'s' if noches > 1 else ''})",
            cantidad=noches,
            precio_unitario_usd=float(precio_noche),
        )
    ]

    for cargo in estadia.cargos_extras:
        cant = max(cargo.cantidad, 1)
        # Convertimos a Decimal antes de la división para mantener precisión
        monto_decimal = _D(cargo.monto_usd)
        lineas.append(LineaFolio(
            concepto=cargo.nombre_servicio,
            cantidad=cant,
            precio_unitario_usd=float(monto_decimal / _D(cant)),
        ))

    # CÁLCULOS FINANCIEROS CON DECIMAL
    # 1. Sumamos los totales de cada línea (asumiendo que LineaFolio.total_usd hace cant * precio)
    subtotal_exacto = sum(_D(l.cantidad) * _D(l.precio_unitario_usd) for l in lineas)
    
    # 2. Calcular IVA y Total
    factor_iva = _D(config.porcentaje_iva) / _D("100")
    total_exacto = subtotal_exacto * (_D("1") + factor_iva)

    # 3. Redondear el TOTAL (Este es el valor real a cobrar)
    total_redondeado = total_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    # 4. Redondear el SUBTOTAL
    subtotal_redondeado = subtotal_exacto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 5. El IVA es la diferencia técnica para que la suma sea perfecta
    iva_redondeado = total_redondeado - subtotal_redondeado

    return ResultadoFolio(
        lineas=lineas,
        subtotal_usd=float(subtotal_redondeado),
        iva_usd=float(iva_redondeado),
        total_usd=float(total_redondeado),
        total_bs=round(float(total_redondeado) * config.tasa_cambio, 2),
        noches=noches,
        precio_noche_usd=float(precio_noche),
        porcentaje_iva=config.porcentaje_iva,
        tasa_cambio=config.tasa_cambio,
    )


def calcular_pagado_bd(estadia) -> float:
    """
    Suma todos los pagos ya grabados en la BD para una estadia.
    Los registros con es_devolucion=True (vueltos) restan del total.

    Args:
        estadia: Objeto Estadia con relacion pagos cargada.
    """
    return round(sum(
        -p.monto_usd if p.es_devolucion else p.monto_usd
        for p in estadia.pagos
    ), 2)


def calcular_saldo(
    total_usd:     float,
    pagado_bd_usd: float,
    pagos_sesion:  Optional[List[dict]] = None,
) -> float:
    """
    Calcula el saldo pendiente en tiempo real combinando lo de la BD
    con los pagos de la sesion actual (aun no grabados).

    Args:
        total_usd:     Total a cobrar (ya incluye IVA).
        pagado_bd_usd: Suma de pagos ya grabados en la BD.
        pagos_sesion:  Lista de dicts de la sesion actual.
                       Cada dict debe tener la clave "monto_usd".

    Returns:
        Saldo en USD:
          > 0  -> falta por cobrar
          aprox 0 -> cuenta saldada exactamente
          < 0  -> sobrante (el cliente pago de mas)
    """
    abonado_sesion = sum(p["monto_usd"] for p in (pagos_sesion or []))
    return round(total_usd - pagado_bd_usd - abonado_sesion, 2)


def a_bs(monto_usd: float, tasa: float) -> float:
    """Convierte USD a Bs usando la tasa vigente."""
    return round(monto_usd * tasa, 2)


def a_usd(monto_bs: float, tasa: float) -> float:
    """Convierte Bs a USD usando la tasa vigente. Protegido contra tasa=0."""
    return round(monto_bs / tasa, 2) if tasa else 0.0