# utils/helpers.py

import bcrypt
from datetime import datetime
from typing import Optional


def hashear_contrasena(contrasena: str) -> str:
    """Genera un hash seguro de la contraseña usando bcrypt."""
    sal = bcrypt.gensalt()
    return bcrypt.hashpw(contrasena.encode('utf-8'), sal).decode('utf-8')


def verificar_contrasena(contrasena: str, hash_guardado: str) -> bool:
    """Compara una contraseña en texto plano con su hash almacenado."""
    return bcrypt.checkpw(contrasena.encode('utf-8'), hash_guardado.encode('utf-8'))


def cargar_configuracion_bd(sesion_bd) -> dict:
    """
    Lee toda la tabla de configuración y devuelve un diccionario clave→valor.
    Si la tabla no existe o está vacía, retorna valores por defecto.
    """
    from database.models import Configuracion

    config = {}
    try:
        registros = sesion_bd.query(Configuracion).all()
        for registro in registros:
            config[registro.clave] = registro.valor
    except Exception:
        # Valores por defecto si la BD aún no está inicializada
        config = {
            "exchange_rate": "35.50",
            "hotel_name":    "Mi Hotel",
            "tax_percentage": "0",
        }
    return config


def formatear_moneda(monto: float, moneda: str = "USD") -> str:
    """Devuelve el monto formateado con su símbolo de moneda."""
    if moneda == "USD":
        return f"${monto:.2f}"
    return f"Bs. {monto:,.2f}"


def parsear_fecha(texto_fecha: str) -> Optional[datetime]:
    """Convierte una cadena 'YYYY-MM-DD' a datetime. Devuelve None si el formato es inválido."""
    try:
        return datetime.strptime(texto_fecha, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None