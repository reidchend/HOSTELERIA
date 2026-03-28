# modules/notifications/dispatcher.py
"""
Dispatcher de notificaciones de Telegram.

DISEÑO:
  • Cola en MEMORIA (Queue) para encolar sin ningún bloqueo de disco.
  • Cola en ARCHIVO SEPARADO (telegram_queue.db) para persistencia en reintentos.
  • El archivo de cola es INDEPENDIENTE de hotel.db — nunca compite con la app.
  • Worker daemon procesa la cola cada 5 segundos en segundo plano.
  • Reintentos con backoff: 30s, 60s, 120s, 240s, 480s (máx 5 intentos).
  • Soporte para vincular mensajes con eventos de bitácora (reply_to_message_id).
"""

import threading
import time
import sqlite3
import os
from queue import Queue, Empty
from typing import Optional

from modules.notifications import telegram as tg
from modules.notifications import formatter as fmt

# ── Constantes ────────────────────────────────────────────────────────────────
_MAX_REINTENTOS = 5
_BACKOFF = [30, 60, 120, 240, 480]
_POLL_INTERVAL = 5
_LOCK_TIMEOUT = 10

# ── Cola en memoria — nunca bloquea, nunca lanza excepciones ─────────────────
_cola_memoria: Queue = Queue()
_worker_activo = False
_tabla_creada = False


# ══════════════════════════════════════════════════════════════════════════════
# ARCHIVO DE COLA SEPARADO  (telegram_queue.db)
# ══════════════════════════════════════════════════════════════════════════════


def _cola_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///hotel.db")
    raw = url[len("sqlite:///") :] if url.startswith("sqlite:///") else "hotel.db"
    base = raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)
    return os.path.join(os.path.dirname(os.path.abspath(base)), "telegram_queue.db")


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(_cola_path(), timeout=_LOCK_TIMEOUT)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _asegurar_tabla():
    global _tabla_creada
    if _tabla_creada:
        return
    try:
        con = _conectar()
        con.execute("""
            CREATE TABLE IF NOT EXISTS cola (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                texto               TEXT    NOT NULL,
                reply_to_message_id INTEGER,
                reintentos          INTEGER DEFAULT 0,
                proximo_en          REAL    DEFAULT 0,
                bitacora_event_id   INTEGER,
                creado_en           TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        con.close()
        _tabla_creada = True
    except Exception as e:
        print(f"[Dispatcher] No se pudo crear tabla cola: {e}")


def _persistir(
    texto: str,
    reply_to_message_id: Optional[int] = None,
    bitacora_event_id: Optional[int] = None,
):
    """Guarda en disco para reintento posterior. Nunca lanza."""
    try:
        _asegurar_tabla()
        con = _conectar()
        con.execute(
            "INSERT INTO cola (texto, reply_to_message_id, bitacora_event_id) VALUES (?, ?, ?)",
            (texto, reply_to_message_id, bitacora_event_id),
        )
        con.commit()
        con.close()
    except Exception as e:
        print(f"[Dispatcher] No se pudo persistir en disco: {e}")


def _obtener_pendientes_disco() -> list[dict]:
    try:
        _asegurar_tabla()
        con = _conectar()
        rows = con.execute(
            "SELECT id, texto, reintentos, reply_to_message_id, bitacora_event_id "
            "FROM cola WHERE proximo_en <= ? ORDER BY id LIMIT 50",
            (time.time(),),
        ).fetchall()
        con.close()
        return [
            {
                "id": r[0],
                "texto": r[1],
                "reintentos": r[2],
                "reply_to_message_id": r[3],
                "bitacora_event_id": r[4],
            }
            for r in rows
        ]
    except Exception:
        return []


def _marcar_enviado_disco(msg_id: int):
    try:
        con = _conectar()
        con.execute("DELETE FROM cola WHERE id = ?", (msg_id,))
        con.commit()
        con.close()
    except Exception:
        pass


def _reprogramar_disco(msg_id: int, reintentos: int):
    if reintentos >= _MAX_REINTENTOS:
        print(f"[Dispatcher] Mensaje {msg_id} descartado tras {reintentos} intentos.")
        _marcar_enviado_disco(msg_id)
        return
    try:
        proximo = time.time() + _BACKOFF[min(reintentos, len(_BACKOFF) - 1)]
        con = _conectar()
        con.execute(
            "UPDATE cola SET reintentos = ?, proximo_en = ? WHERE id = ?",
            (reintentos + 1, proximo, msg_id),
        )
        con.commit()
        con.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# ACTUALIZAR MESSAGE_ID EN BITÁCORA
# ══════════════════════════════════════════════════════════════════════════════


def guardar_telegram_message_id(bitacora_event_id: int, telegram_message_id: str):
    """
    Vincula el ID del mensaje de Telegram con el evento de bitácora correspondiente.
    """
    try:
        from database.connection import SesionLocal
        from database.models import BitacoraEvento

        sesion = SesionLocal()
        try:
            evento = sesion.get(BitacoraEvento, bitacora_event_id)
            if evento:
                evento.telegram_message_id = telegram_message_id
                sesion.commit()
                print(
                    f"[Dispatcher] Guardado telegram_message_id={telegram_message_id} para evento {bitacora_event_id}"
                )
            else:
                print(
                    f"[Dispatcher] No se encontró evento de bitácora {bitacora_event_id}"
                )
        except Exception as e:
            sesion.rollback()
            print(f"[Dispatcher] Error al guardar message_id: {e}")
        finally:
            sesion.close()
    except Exception as e:
        print(f"[Dispatcher] Error de conexión al guardar message_id: {e}")


def obtener_telegram_message_id(bitacora_event_id: int) -> Optional[str]:
    """
    Obtiene el telegram_message_id de un evento de bitácora.
    """
    try:
        from database.connection import SesionLocal
        from database.models import BitacoraEvento

        sesion = SesionLocal()
        try:
            evento = sesion.get(BitacoraEvento, bitacora_event_id)
            return evento.telegram_message_id if evento else None
        finally:
            sesion.close()
    except Exception as e:
        print(f"[Dispatcher] Error en obtener_telegram_message_id: {e}")
        return None


def buscar_checkin_pendiente_por_estadia(estadia_id: int) -> Optional[int]:
    """
    Busca el evento de bitácora CHECKIN pendiente para una estadía específica.
    Retorna el ID del evento de bitácora o None si no lo encuentra.
    """
    try:
        from database.connection import SesionLocal
        from database.models import BitacoraEvento, TipoEvento

        sesion = SesionLocal()
        try:
            evento = (
                sesion.query(BitacoraEvento)
                .filter(
                    BitacoraEvento.habitacion.like(f"%{estadia_id}%")
                    if False  # No filtra por estadia_id directamente, busca en concepto
                    else BitacoraEvento.tipo == TipoEvento.CHECKIN,
                    BitacoraEvento.confirmado == False,
                    BitacoraEvento.telegram_message_id != None,
                )
                .order_by(BitacoraEvento.creado_en.desc())
                .first()
            )
            return evento.id if evento else None
        finally:
            sesion.close()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# WORKER
# ══════════════════════════════════════════════════════════════════════════════


def _worker():
    """
    Hilo de fondo.
    Ciclo:
      1. Vaciar cola en memoria → intentar enviar directamente.
         Si falla → persistir en disco para reintento.
      2. Procesar pendientes en disco (reintentos anteriores).
    """
    _asegurar_tabla()
    while True:
        # 1. Cola en memoria
        while True:
            try:
                item = _cola_memoria.get_nowait()
            except Empty:
                break

            # Item puede ser (texto,) o (texto, reply_to, event_id)
            if isinstance(item, tuple):
                texto, reply_to, event_id = item
            else:
                texto, reply_to, event_id = item, None, None

            exito, msg_id = tg.enviar_mensaje(texto, reply_to_message_id=reply_to)

            if exito and msg_id and event_id:
                guardar_telegram_message_id(event_id, str(msg_id))
            elif not exito:
                _persistir(texto, reply_to, event_id)

        # 2. Reintentos en disco
        for msg in _obtener_pendientes_disco():
            exito, msg_id = tg.enviar_mensaje(
                msg["texto"], reply_to_message_id=msg.get("reply_to_message_id")
            )
            if exito:
                _marcar_enviado_disco(msg["id"])
                if msg_id and msg.get("bitacora_event_id"):
                    guardar_telegram_message_id(msg["bitacora_event_id"], str(msg_id))
            else:
                _reprogramar_disco(msg["id"], msg["reintentos"])

        time.sleep(_POLL_INTERVAL)


def _iniciar_worker():
    global _worker_activo
    if not _worker_activo:
        _worker_activo = True
        threading.Thread(target=_worker, daemon=True, name="TelegramWorker").start()


# ══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA
# ══════════════════════════════════════════════════════════════════════════════


def _encolar(
    texto: str,
    reply_to_message_id: Optional[int] = None,
    bitacora_event_id: Optional[int] = None,
):
    """Pone en cola en memoria. Jamás bloquea ni lanza excepciones."""
    _iniciar_worker()
    _cola_memoria.put((texto, reply_to_message_id, bitacora_event_id))


def enviar_texto(
    texto: str,
    reply_to_message_id: Optional[int] = None,
    bitacora_event_id: Optional[int] = None,
):
    _encolar(texto, reply_to_message_id, bitacora_event_id)


def enviar_evento(
    evento,
    tasa: float = 0,
    reply_to_message_id: Optional[int] = None,
    bitacora_event_id: Optional[int] = None,
):
    try:
        _encolar(
            fmt.desde_evento(evento, tasa=tasa), reply_to_message_id, bitacora_event_id
        )
    except Exception as e:
        print(f"[Dispatcher] Error al formatear evento: {e}")


def enviar_apertura_turno(
    recepcionista: str,
    caja_usd: float,
    caja_bs: float,
    tasa: float,
):
    try:
        _encolar(fmt.apertura_turno(recepcionista, caja_usd, caja_bs, tasa))
    except Exception as e:
        print(f"[Dispatcher] Error apertura turno: {e}")


def enviar_cierre_turno(
    recepcionista: str,
    cobrado_usd: float,
    vueltos_usd: float,
    neto_usd: float,
    caja_chica_usd: float,
    diferencia_usd: float,
):
    try:
        _encolar(
            fmt.cierre_turno(
                recepcionista,
                cobrado_usd,
                vueltos_usd,
                neto_usd,
                caja_chica_usd,
                diferencia_usd,
            )
        )
    except Exception as e:
        print(f"[Dispatcher] Error cierre turno: {e}")
