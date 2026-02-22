# utils/helpers.py

import bcrypt
import json
from datetime import datetime
from typing import Optional

def hash_password(password: str) -> str:
    """Hashea una contraseña usando bcrypt"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verifica si una contraseña coincide con su hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def load_config_from_db(db_session):
    """Carga la configuración desde la base de datos"""
    from database.models import Configuration
    
    config = {}
    try:
        configurations = db_session.query(Configuration).all()
        for conf in configurations:
            config[conf.key] = conf.value
    except:
        # Si la tabla no existe o está vacía, devolver config por defecto
        config = {
            "exchange_rate": "35.50",
            "hotel_name": "Mi Hotel",
            "currency_symbol": "$",
            "local_currency": "Bs."
        }
    return config

def format_currency(amount: float, currency: str = "USD") -> str:
    """Formatea un monto como moneda"""
    if currency == "USD":
        return f"${amount:.2f}"
    else:
        return f"Bs. {amount:.2f}"

def parse_date(date_str: str) -> Optional[datetime]:
    """Convierte string a datetime si es válido"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except:
        return None