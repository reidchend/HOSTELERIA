# modules/rooms/importar_reservaciones.py
"""
Importa reservaciones desde Google Sheets.

La Sheet debe ser pública (modo lectura).
El sistema lee el CSV, crea las Reservacion con estado PENDIENTE
y solo procesa filas donde la columna "importado" == "NO".

Para marcar filas como importadas en la Sheet, el Apps Script
expone un endpoint GET /marcar?fila=N que actualiza la celda.
"""

import urllib.request
import urllib.parse
import csv
import io
from datetime import datetime
from database.connection import SesionLocal
from database.models import Reservacion, EstadoReservacion, Configuracion


# Intentamos primero con export (requiere que la hoja sea pública via Archivo→Publicar)
# Si falla, usamos gviz que funciona con "compartir con cualquiera"
_CSV_URL      = "https://docs.google.com/spreadsheets/d/{id}/export?format=csv"
_CSV_URL_GVIZ = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv"
_ELIMINAR_URL = "{script_url}?action=eliminar&fila={fila}"


def importar(sheet_id: str, script_url: str = "") -> dict:
    """
    Lee la Sheet, importa filas nuevas (importado == "NO").
    Si se pasa script_url, marca cada fila importada en la Sheet.
    Devuelve {importadas, errores, detalle_errores}.
    """
    contenido = None
    ultimo_error = ""
    for url_tmpl in [_CSV_URL_GVIZ, _CSV_URL]:
        url = url_tmpl.format(id=sheet_id)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                contenido = r.read().decode("utf-8")
            break   # éxito — salir del loop
        except urllib.error.HTTPError as e:
            ultimo_error = f"HTTP {e.code}"
        except Exception as e:
            ultimo_error = str(e)

    if contenido is None:
        return {"importadas": 0, "errores": 1,
                "detalle_errores": [
                    f"No se pudo leer la Sheet ({ultimo_error}). Verifica:\n"
                    "  1. Sheet ID correcto.\n"
                    "  2. Compartir → Cualquier persona con el enlace → Lector."
                ]}

    filas = list(csv.DictReader(io.StringIO(contenido)))

    sesion     = SesionLocal()
    importadas = 0
    errores    = []

    try:
        for idx, fila in reversed(list(enumerate(filas, start=2))):
            if fila.get("importado", "").strip().upper() != "NO":
                continue

            try:
                entrada = datetime.strptime(
                    fila.get("fecha_entrada", "").strip(), "%Y-%m-%d").date()
                salida  = datetime.strptime(
                    fila.get("fecha_salida",  "").strip(), "%Y-%m-%d").date()
            except ValueError as e:
                errores.append(f"Fila {idx}: fecha inválida — {e}")
                continue

            if salida <= entrada:
                errores.append(f"Fila {idx}: salida ≤ entrada")
                continue

            nombre   = fila.get("nombre",   "").strip()
            apellido = fila.get("apellido", "").strip()
            tipo     = fila.get("tipo_habitacion", "").strip()

            if not nombre or not apellido or not tipo:
                errores.append(f"Fila {idx}: faltan campos obligatorios")
                continue

            sesion.add(Reservacion(
                nombre          = nombre,
                apellido        = apellido,
                documento       = fila.get("documento",    "").strip() or None,
                telefono        = fila.get("telefono",     "").strip() or None,
                email           = fila.get("email",        "").strip() or None,
                nacionalidad    = fila.get("nacionalidad", "").strip() or None,
                tipo_habitacion = tipo,
                fecha_entrada   = entrada,
                fecha_salida    = salida,
                num_huespedes   = int(fila.get("num_huespedes", "1") or 1),
                notas           = fila.get("notas", "").strip() or None,
                estado          = EstadoReservacion.PENDIENTE,
                origen          = "web",
            ))
            importadas += 1

            # Marcar fila en la Sheet (no bloquea si falla)
            if script_url:
                try:
                    # Usamos la nueva constante _ELIMINAR_URL
                    mark_url = _ELIMINAR_URL.format(
                        script_url=script_url, fila=idx)
                    urllib.request.urlopen(mark_url, timeout=5)
                except Exception:
                    pass

        sesion.commit()
    except Exception as e:
        sesion.rollback()
        errores.append(f"Error al guardar: {e}")
    finally:
        sesion.close()

    return {
        "importadas":      importadas,
        "errores":         len(errores),
        "detalle_errores": errores,
    }


def leer_config(sesion) -> dict:
    """Lee sheet_id y script_url guardados en Configuracion."""
    def _val(clave):
        c = sesion.query(Configuracion).filter(
            Configuracion.clave == clave).first()
        return c.valor.strip() if c and c.valor else ""

    return {
        "sheet_id":   _val("google_sheet_id"),
        "script_url": _val("google_script_url"),
    }


def guardar_config(sesion, sheet_id: str, script_url: str):
    """Guarda sheet_id y script_url en Configuracion."""
    for clave, valor, desc in [
        ("google_sheet_id",   sheet_id,
         "ID de la Google Sheet de reservaciones web"),
        ("google_script_url", script_url,
         "URL del Google Apps Script Web App"),
    ]:
        c = sesion.query(Configuracion).filter(
            Configuracion.clave == clave).first()
        if c:
            c.valor = valor
        else:
            sesion.add(Configuracion(clave=clave, valor=valor, descripcion=desc))