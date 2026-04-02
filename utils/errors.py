# utils/errors.py
"""
Utilidades para manejo centralizado de errores.

Proporciona funciones para mostrar errores tanto en UI (snackbar)
como en consola (print) de forma unificada.
"""

import traceback
import flet as ft


def handle_error(
    e: Exception,
    pagina: ft.Page = None,
    contexto: str = "",
    mostrar_snackbar: bool = True,
) -> str:
    """
    Maneja un error de forma unificada: muestra snackbar y print en consola.
    
    Args:
        e: La excepción capturada
        pagina: Página de Flet para mostrar snackbar (opcional)
        contexto: Descripción breve de dónde ocurrió el error
        mostrar_snackbar: Si True, muestra snackbar en la página
    
    Returns:
        str: Mensaje de error formateado
    """
    msg = f"Error{' - ' + contexto if contexto else ''}: {type(e).__name__}: {str(e)}"
    
    # Print en consola con traceback completo
    print(f"\n❌ {msg}")
    print("📋 Traceback:")
    traceback.print_exc()
    print("-" * 50)
    
    # Mostrar en UI si se proporciona página
    if mostrar_snackbar and pagina:
        pagina.show_snack_bar(
            ft.SnackBar(
                content=ft.Text(msg),
                bgcolor=ft.Colors.RED_800,
                duration=5000,
            )
        )
    
    return msg


def log_error(contexto: str, *args) -> None:
    """
    Loguea un error o advertencia a consola.
    
    Uso:
        log_error("Check-in falló", habitacion_id, error_details)
    """
    print(f"\n⚠️  {contexto}: " + " | ".join(str(a) for a in args))


def log_info(contexto: str, *args) -> None:
    """
    Loguea información a consola.
    
    Uso:
        log_info("Check-in exitoso", habitacion_id, huesped)
    """
    print(f"ℹ️  {contexto}: " + " | ".join(str(a) for a in args))


__all__ = ["handle_error", "log_error", "log_info"]
