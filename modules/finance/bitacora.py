# modules/finance/bitacora.py
"""
Helper centralizado para registrar eventos en la bitácora del turno.

Uso desde cualquier módulo:
    from modules.finance.bitacora import registrar

    registrar(
        sesion      = sesion,          # sesión SQLAlchemy abierta
        pagina      = self.pagina,     # ft.Page para leer el turno de sesión
        tipo        = TipoEvento.PAGO,
        concepto    = "Hab. 26 — Cobro de hospedaje",
        habitacion  = "26",
        monto_usd   = 25.00,
        monto_bs    = 11075.00,
        metodo_pago = "Pago Móvil",
        referencia  = "Ref: 0186 Tlf: 80",
        confirmado  = True,
    )

    # El commit lo hace el módulo llamador — registrar() solo hace add().
"""

from datetime import datetime
from decimal import Decimal
from database.models import BitacoraEvento, TipoEvento


def registrar(
    sesion,
    pagina,
    tipo:          TipoEvento,
    concepto:      str,
    habitacion:    str  = "",
    monto_usd            = 0,
    monto_bs             = 0,
    metodo_pago:   str  = "",
    referencia:    str  = "",
    recepcionista: str  = "",
    confirmado:    bool = True,
) -> BitacoraEvento:
    """
    Crea un BitacoraEvento y lo agrega a la sesión (sin commit).
    Obtiene el turno_id desde pagina.session; si no hay turno activo
    usa -1 para no bloquear la operación.
    """
    try:
        turno_id = pagina.session.get("id_turno_actual") or -1
    except Exception:
        turno_id = -1

    # Recepcionista: intentar desde sesión de página si no se pasó
    if not recepcionista:
        try:
            usuario = pagina.session.get("usuario_activo") or {}
            recepcionista = usuario.get("nombre_completo", "")
        except Exception:
            recepcionista = ""

    evento = BitacoraEvento(
        turno_id      = turno_id,
        tipo          = tipo,
        habitacion    = habitacion,
        concepto      = concepto,
        monto_usd     = Decimal(str(monto_usd)) if monto_usd else Decimal("0"),
        monto_bs      = Decimal(str(monto_bs))  if monto_bs  else Decimal("0"),
        metodo_pago   = metodo_pago,
        referencia    = referencia,
        recepcionista = recepcionista,
        confirmado    = confirmado,
        creado_en     = datetime.now(),
    )
    sesion.add(evento)
    return evento