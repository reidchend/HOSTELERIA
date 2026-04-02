# utils/__init__.py
"""
Utilidades centralizadas del proyecto.

Exporta los helpers más usados para facilitar imports.
"""

from utils.decimal_utils import Decimal, D, round_decimal, to_float
from utils.db import sesion, ejecutar
from utils.errors import handle_error, log_error, log_info
from utils.calculos_financieros import (
    ConfigFinanciera,
    leer_config_financiera,
    get_config_cache,
    a_bs,
    a_usd,
    a_bs_decimal,
    a_usd_decimal,
)
from utils.helpers import (
    hashear_contrasena,
    verificar_contrasena,
    cargar_configuracion_bd,
    formatear_moneda,
    parsear_fecha,
)

__all__ = [
    "Decimal",
    "D",
    "round_decimal",
    "to_float",
    "sesion",
    "ejecutar",
    "handle_error",
    "log_error",
    "log_info",
    "ConfigFinanciera",
    "leer_config_financiera",
    "get_config_cache",
    "a_bs",
    "a_usd",
    "a_bs_decimal",
    "a_usd_decimal",
    "hashear_contrasena",
    "verificar_contrasena",
    "cargar_configuracion_bd",
    "formatear_moneda",
    "parsear_fecha",
]
