# utils/validators.py

import re
from typing import Tuple


def validar_documento(documento: str) -> Tuple[bool, str]:
    """
    Valida cédula o pasaporte venezolano.
    Formatos aceptados: V12345678 · E12345678 · J12345678 · AA123456789 · 12345678
    """
    patrones = [
        r'^[VEJ]\d{6,8}$',       # Venezolano / extranjero / jurídico
        r'^[A-Z]{2}\d{6,9}$',    # Pasaporte internacional
        r'^\d{6,8}$',            # Solo números
    ]
    for patron in patrones:
        if re.match(patron, documento.upper()):
            return True, documento.upper()
    return False, "Formato de documento inválido"


def validar_telefono(telefono: str) -> Tuple[bool, str]:
    """
    Valida número telefónico venezolano.
    Acepta: 04121234567 · 04241234567 · +584121234567 · 02121234567
    """
    telefono = telefono.replace(" ", "").replace("-", "")
    patron = r'^(?:\+58|0)(?:212|412|414|424|416|426)\d{7}$'
    if re.match(patron, telefono):
        return True, telefono
    return False, "Número telefónico inválido"


def validar_correo(correo: str) -> Tuple[bool, str]:
    """Valida que la dirección de correo electrónico tenga formato válido."""
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(patron, correo):
        return True, correo.lower()
    return False, "Correo electrónico inválido"


def validar_campos_requeridos(datos: dict, campos_requeridos: list) -> Tuple[bool, str]:
    """Verifica que todos los campos de la lista estén presentes y no vacíos."""
    for campo in campos_requeridos:
        if campo not in datos or not datos[campo]:
            return False, f"El campo '{campo}' es requerido"
    return True, "OK"