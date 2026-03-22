# modules/notifications/dispatcher.py
"""
Dispatcher de notificaciones de Telegram.

DISEÑO:
  • Cola en MEMORIA (Queue) para encolar sin ningún bloqueo de disco.
  • Cola en ARCHIVO SEPARADO (telegram_queue.db) para persistencia en reintentos.
  • El archivo de cola es INDEPENDIENTE de hotel.db — nunca compite con la app.
  • Worker daemon procesa la cola cada 5 segundos en segundo plano.
  • Reintentos con backoff: 30s, 60s, 120s, 240s, 480s (máx 5 intentos).
"""

import threading
import time
import sqlite3
import os
from queue import Queue, Empty

from modules.notifications import telegram as tg
from modules.notifications import formatter as fmt

# ── Constantes ────────────────────────────────────────────────────────────────
_MAX_REINTENTOS = 5
_BACKOFF        = [30, 60, 120, 240, 480]
_POLL_INTERVAL  = 5
_LOCK_TIMEOUT   = 10

# ── Cola en memoria — nunca bloquea, nunca lanza excepciones ─────────────────
_cola_memoria: Queue = Queue()
_worker_activo = False
_tabla_creada  = False


# ══════════════════════════════════════════════════════════════════════════════
# ARCHIVO DE COLA SEPARADO  (telegram_queue.db)
# ══════════════════════════════════════════════════════════════════════════════

def _cola_path() -> str:
    url  = os.getenv("DATABASE_URL", "sqlite:///hotel.db")
    raw  = url[len("sqlite:///"):] if url.startswith("sqlite:///") else "hotel.db"
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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                texto       TEXT    NOT NULL,
                reintentos  INTEGER DEFAULT 0,
                proximo_en  REAL    DEFAULT 0,
                creado_en   TEXT    DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        con.close()
        _tabla_creada = True
    except Exception as e:
        print(f"[Dispatcher] No se pudo crear tabla cola: {e}")


def _persistir(texto: str):
    """Guarda en disco para reintento posterior. Nunca lanza."""
    try:
        _asegurar_tabla()
        con = _conectar()
        con.execute("INSERT INTO cola (texto) VALUES (?)", (texto,))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[Dispatcher] No se pudo persistir en disco: {e}")


def _obtener_pendientes_disco() -> list[dict]:
    try:
        _asegurar_tabla()
        con  = _conectar()
        rows = con.execute(
            "SELECT id, texto, reintentos FROM cola WHERE proximo_en <= ? ORDER BY id LIMIT 50",
            (time.time(),),
        ).fetchall()
        con.close()
        return [{"id": r[0], "texto": r[1], "reintentos": r[2]} for r in rows]
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
        con     = _conectar()
        con.execute(
            "UPDATE cola SET reintentos = ?, proximo_en = ? WHERE id = ?",
            (reintentos + 1, proximo, msg_id),
        )
        con.commit()
        con.close()
    except Exception:
        pass


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
                texto = _cola_memoria.get_nowait()
            except Empty:
                break
            if not tg.enviar_mensaje(texto):
                _persistir(texto)

        # 2. Reintentos en disco
        for msg in _obtener_pendientes_disco():
            if tg.enviar_mensaje(msg["texto"]):
                _marcar_enviado_disco(msg["id"])
            else:
                _reprogramar_disco(msg["id"], msg["reintentos"])

        time.sleep(_POLL_INTERVAL)


def _iniciar_worker():
    global _worker_activo
    if not _worker_activo:
        _worker_activo = True
        threading.Thread(
            target=_worker, daemon=True, name="TelegramWorker"
        ).start()


# ══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA
# ══════════════════════════════════════════════════════════════════════════════

def _encolar(texto: str):
    """Pone en cola en memoria. Jamás bloquea ni lanza excepciones."""
    _iniciar_worker()
    _cola_memoria.put(texto)


def enviar_texto(texto: str):
    _encolar(texto)


def enviar_evento(evento, tasa: float = 0):
    try:
        _encolar(fmt.desde_evento(evento, tasa=tasa))
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
        _encolar(fmt.cierre_turno(
            recepcionista, cobrado_usd, vueltos_usd,
            neto_usd, caja_chica_usd, diferencia_usd,
        ))
    except Exception as e:
        print(f"[Dispatcher] Error cierre turno: {e}")