# modules/finance/bitacora.py
"""
Helper centralizado para registrar eventos en la bitácora del turno
y enviarlos automáticamente a Telegram.

Uso desde cualquier módulo:
    from modules.finance.bitacora import registrar

    registrar(
        sesion      = sesion,
        pagina      = self.pagina,
        tipo        = TipoEvento.PAGO,
        concepto    = "Hab. 26 — Cobro de hospedaje",
        habitacion  = "26",
        monto_usd   = 25.00,
        monto_bs    = 11075.00,
        metodo_pago = "Pago Móvil",
        referencia  = "Ref: 0186 Tlf: 80",
        confirmado  = True,
    )

    # Para suprimir la notificación de Telegram (cuando el módulo
    # llamador la gestiona con un mensaje más específico):
    registrar(..., notificar_telegram=False)

    # El commit lo hace el módulo llamador — registrar() solo hace add().
"""

from datetime import datetime
from decimal import Decimal
from database.models import BitacoraEvento, TipoEvento


def registrar(
    sesion,
    pagina,
    tipo: TipoEvento,
    concepto: str,
    habitacion: str = "",
    monto_usd=0,
    monto_bs=0,
    metodo_pago: str = "",
    referencia: str = "",
    recepcionista: str = "",
    confirmado: bool = True,
    notificar_telegram: bool = True,
    retornar_evento: bool = False,
) -> BitacoraEvento:
    """
    Crea un BitacoraEvento y lo agrega a la sesión (sin commit).

    notificar_telegram=False: registra en BD pero NO encola notificación.
    Útil cuando el módulo llamador envía un mensaje más específico por su cuenta.
    """
    try:
        turno_id = pagina.session.get("id_turno_actual") or -1
    except Exception:
        turno_id = -1

    if not recepcionista:
        try:
            usuario = pagina.session.get("usuario_activo") or {}
            recepcionista = usuario.get("nombre_completo", "")
        except Exception:
            recepcionista = ""

    tasa = 0.0
    try:
        tasa = float(pagina.session.get("tasa_cambio") or 0)
    except Exception:
        pass

    evento = BitacoraEvento(
        turno_id=turno_id,
        tipo=tipo,
        habitacion=habitacion,
        concepto=concepto,
        monto_usd=Decimal(str(monto_usd)) if monto_usd else Decimal("0"),
        monto_bs=Decimal(str(monto_bs)) if monto_bs else Decimal("0"),
        metodo_pago=metodo_pago,
        referencia=referencia,
        recepcionista=recepcionista,
        confirmado=confirmado,
        creado_en=datetime.now(),
    )
    sesion.add(evento)
    sesion.flush()

    # ── Telegram ──────────────────────────────────────────────────────────────
    if notificar_telegram:
        try:
            from modules.notifications.dispatcher import enviar_evento

            enviar_evento(
                {
                    "tipo": tipo,
                    "habitacion": habitacion,
                    "concepto": concepto,
                    "monto_usd": float(monto_usd) if monto_usd else 0.0,
                    "monto_bs": float(monto_bs) if monto_bs else 0.0,
                    "metodo_pago": metodo_pago,
                    "referencia": referencia,
                    "recepcionista": recepcionista,
                    "confirmado": confirmado,
                },
                tasa=tasa,
            )
        except Exception as e:
            print(f"[Bitacora] Error al encolar notificación: {e}")

    return evento
