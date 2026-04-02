# utils/db.py
"""
Utilidades centralizadas para gestión de sesiones de base de datos.

Proporciona un context manager para manejar sesiones de forma segura,
evitando fugas de conexión.
"""

from contextlib import contextmanager
from database.connection import SesionLocal


@contextmanager
def sesion():
    """
    Context manager para sesiones de BD.
    
    Uso:
        with sesion() as s:
            s.query(...)
            s.commit()
    
    Garantiza cierre automático incluso si hay excepción.
    """
    sesion = SesionLocal()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def ejecutar(func):
    """
    Decorador para funciones que necesitan sesión automáticamente.
    
    Uso:
        @ejecutar
        def mi_funcion(sesion):
            return sesion.query(...)
    
    La función recibe la sesión y el resultado se retorna automáticamente.
    """
    def wrapper(*args, **kwargs):
        with sesion() as s:
            return func(s, *args, **kwargs)
    return wrapper


__all__ = ["sesion", "ejecutar"]
