# modules/notifications/telegram.py
"""
Cliente HTTP para la Bot API de Telegram.
Usa únicamente urllib (stdlib) — sin dependencias externas.

Configuración (por orden de prioridad):
  1. Tabla Configuracion en BD  (clave: telegram_bot_token / telegram_chat_id)
  2. Variables de entorno       (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)
  3. Archivo .env               (cargado por python-dotenv al iniciar la app)
"""

import json
import urllib.request
import urllib.error
import os
from typing import Optional

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _leer_credenciales_bd() -> tuple[str, str]:
    """
    Lee token y chat_id desde la tabla Configuracion.
    Devuelve ("", "") si no están disponibles o la BD falla.
    """
    try:
        from database.connection import SesionLocal
        from database.models import Configuracion

        sesion = SesionLocal()
        try:

            def _val(clave):
                c = (
                    sesion.query(Configuracion)
                    .filter(Configuracion.clave == clave)
                    .first()
                )
                return (c.valor or "").strip() if c else ""

            return _val("telegram_bot_token"), _val("telegram_chat_id")
        finally:
            sesion.close()
    except Exception:
        return "", ""


def obtener_credenciales() -> tuple[str, str]:
    """
    Devuelve (token, chat_id) usando la jerarquía de fuentes:
      1. BD  →  2. Variables de entorno / .env
    """
    token, chat_id = _leer_credenciales_bd()

    if not token:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    return token, chat_id


def enviar_mensaje(
    texto: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    silencioso: bool = True,
    reply_to_message_id: Optional[int] = None,
) -> tuple[bool, Optional[int]]:
    """
    Envía un mensaje al grupo/canal de Telegram.

    Args:
        texto:                Contenido del mensaje (soporta HTML básico: <b>, <i>, <code>).
        token:                Bot token. Si None, se resuelve automáticamente.
        chat_id:              Chat / grupo / canal. Si None, se resuelve automáticamente.
        parse_mode:           "HTML" o "Markdown".
        silencioso:           True = sin sonido de notificación en el cliente.
        reply_to_message_id:  ID del mensaje al que se responde (para encadenar mensajes).

    Returns:
        (True, message_id) si el envío fue exitoso
        (False, None) si falló
    """
    if token is None or chat_id is None:
        tok, cid = obtener_credenciales()
        token = token or tok
        chat_id = chat_id or cid

    if not token or not chat_id:
        return False, None

    url = _API_BASE.format(token=token)
    body_dict = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": parse_mode,
        "disable_notification": silencioso,
    }
    if reply_to_message_id:
        body_dict["reply_to_message_id"] = reply_to_message_id

    body = json.dumps(body_dict).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            respuesta = json.loads(resp.read())
            if respuesta.get("ok"):
                msg_id = respuesta.get("result", {}).get("message_id")
                return True, msg_id
            return False, None
    except urllib.error.HTTPError as e:
        try:
            detalle = json.loads(e.read()).get("description", str(e))
        except Exception:
            detalle = str(e)
        print(f"[Telegram] HTTP {e.code}: {detalle}")
        return False, None
    except Exception as e:
        print(f"[Telegram] Error de red: {e}")
        return False, None


def verificar_conexion(token: str, chat_id: str) -> tuple[bool, str]:
    """
    Envía un mensaje de prueba para verificar que las credenciales son correctas.

    Returns:
        (True, "")          → OK
        (False, "mensaje")  → error con descripción
    """
    if not token or not chat_id:
        return False, "Token o Chat ID vacíos."

    url = _API_BASE.format(token=token)
    body = json.dumps(
        {
            "chat_id": chat_id,
            "text": "✅ <b>Conexión verificada</b>\nLa Posada de Daniel C.A. está conectada a Telegram.",
            "parse_mode": "HTML",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                return True, ""
            return False, data.get("description", "Respuesta inesperada de la API.")
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read()).get("description", str(e))
        except Exception:
            desc = str(e)
        return False, f"HTTP {e.code}: {desc}"
    except Exception as e:
        return False, str(e)
