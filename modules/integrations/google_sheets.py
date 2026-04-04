# modules/integrations/google_sheets.py
"""
Integración con Google Sheets para importar reservaciones web.
Usa el Google Apps Script Web App URL configurado en la BD como intermediario,
sin necesidad de credenciales de servicio.
"""
import flet as ft
import requests
from datetime import datetime
from database.connection import SesionLocal
from database.models import Reservacion, EstadoReservacion, Configuracion


def importar_reservaciones_web(pagina: ft.Page) -> int:
    """
    Importa reservaciones desde Google Sheets vía Apps Script Web App.
    Devuelve el número de nuevas reservaciones importadas.
    """
    sesion = SesionLocal()
    try:
        # Obtener URL del Apps Script de la configuración
        cfg = sesion.query(Configuracion).filter(Configuracion.clave == "google_script_url").first()
        if not cfg or not cfg.valor:
            pagina.open(ft.SnackBar(
                ft.Text("Configura la URL del Google Apps Script primero"),
                bgcolor=ft.Colors.RED_700,
            ))
            return 0

        script_url = cfg.valor.strip()

        # Hacer petición al Apps Script
        response = requests.get(script_url, timeout=30)
        response.raise_for_status()
        data = response.json()

        # El Apps Script debe devolver un array de objetos con las reservaciones
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            pagina.open(ft.SnackBar(
                ft.Text("Formato de respuesta inesperado del Apps Script"),
                bgcolor=ft.Colors.RED_700,
            ))
            return 0

        nuevas = 0
        for row in rows:
            nombre = str(row.get("nombre", "") or row.get("Nombre", "")).strip()
            apellido = str(row.get("apellido", "") or row.get("Apellido", "")).strip()
            documento = str(row.get("documento", "") or row.get("Documento", "")).strip()
            telefono = str(row.get("telefono", "") or row.get("Teléfono", "")).strip()
            email = str(row.get("email", "") or row.get("Email", "") or row.get("correo", "")).strip()
            tipo_hab = str(row.get("tipo", "") or row.get("Tipo", "") or row.get("tipo_habitacion", "")).strip()
            fecha_entrada_str = str(row.get("entrada", "") or row.get("Entrada", "") or row.get("fecha_entrada", "")).strip()
            fecha_salida_str = str(row.get("salida", "") or row.get("Salida", "") or row.get("fecha_salida", "")).strip()
            notas = str(row.get("notas", "") or row.get("Notas", "") or row.get("observaciones", "")).strip()
            importada = str(row.get("importada", "") or row.get("Importada", "")).strip()

            if not nombre or not apellido or not tipo_hab:
                continue

            # Verificar si ya fue importada
            if importada.lower() in ["si", "sí", "yes", "true", "1"]:
                continue

            # Parsear fechas
            try:
                fecha_entrada = datetime.strptime(fecha_entrada_str, "%Y-%m-%d").date()
                fecha_salida = datetime.strptime(fecha_salida_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            # Verificar si ya existe
            existente = sesion.query(Reservacion).filter(
                Reservacion.nombre == nombre,
                Reservacion.apellido == apellido,
                Reservacion.documento == documento if documento else True,
                Reservacion.fecha_entrada == fecha_entrada,
            ).first()

            if existente:
                continue

            # Crear reservación
            nueva = Reservacion(
                nombre=nombre,
                apellido=apellido,
                documento=documento or None,
                telefono=telefono or None,
                email=email or None,
                tipo_habitacion=tipo_hab,
                fecha_entrada=fecha_entrada,
                fecha_salida=fecha_salida,
                num_huespedes=1,
                notas=notas or None,
                estado=EstadoReservacion.PENDIENTE,
                origen="web",
            )
            sesion.add(nueva)
            nuevas += 1

        if nuevas > 0:
            sesion.commit()

        return nuevas

    except requests.exceptions.RequestException as e:
        pagina.open(ft.SnackBar(ft.Text(f"Error de conexión con el Apps Script: {e}"), bgcolor=ft.Colors.RED_700))
        return 0
    except Exception as e:
        pagina.open(ft.SnackBar(ft.Text(f"Error al importar: {e}"), bgcolor=ft.Colors.RED_700))
        return 0
    finally:
        sesion.close()
