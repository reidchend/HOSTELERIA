# utils/validators.py

import re
from typing import Tuple, Any

def validate_document(document: str) -> Tuple[bool, str]:
    """Valida cédula/pasaporte venezolano"""
    # Patrones: V12345678, E12345678, J12345678, Pasaporte (letras y números)
    patterns = [
        r'^[VEJ]\d{6,8}$',  # Venezolano/extranjero/jurídico
        r'^[A-Z]{2}\d{6,9}$',  # Pasaporte
        r'^\d{6,8}$'  # Solo números
    ]
    
    for pattern in patterns:
        if re.match(pattern, document.upper()):
            return True, document.upper()
    
    return False, "Formato de documento inválido"

def validate_phone(phone: str) -> Tuple[bool, str]:
    """Valida número telefónico venezolano"""
    # Acepta: 04121234567, 04241234567, +584121234567, 02121234567
    phone = phone.replace(" ", "").replace("-", "")
    pattern = r'^(?:\+58|0)(?:212|412|414|424|416|426)\d{7}$'
    
    if re.match(pattern, phone):
        return True, phone
    return False, "Número telefónico inválido"

def validate_email(email: str) -> Tuple[bool, str]:
    """Valida email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(pattern, email):
        return True, email.lower()
    return False, "Email inválido"

def validate_required_fields(data: dict, required_fields: list) -> Tuple[bool, str]:
    """Valida que los campos requeridos no estén vacíos"""
    for field in required_fields:
        if field not in data or not data[field]:
            return False, f"El campo {field} es requerido"
    return True, "OK"