# modules/notifications/formatter.py
"""
Convierte un BitacoraEvento (o datos sueltos) en un mensaje HTML
listo para enviar a Telegram.

Todos los mensajes siguen esta estructura:
  🏨 <nombre_hotel>
  ━━━━━━━━━━━━━━━━━━━━━
  {EMOJI} <TIPO EN MAYÚSCULAS>
  {líneas de detalle}
  ⏰ HH:MM · dd/mm/aaaa
"""

from datetime import datetime
from database.models import TipoEvento

# ── Cabecera compartida ───────────────────────────────────────────────────────
_HOTEL = "🏨 <b>La Posada de Daniel C.A.</b>"
_SEP   = "━━━━━━━━━━━━━━━━━━━━━"

# ── Config visual por TipoEvento ─────────────────────────────────────────────
_CFG = {
    TipoEvento.CHECKIN:     ("🛎",  "CHECK-IN"),
    TipoEvento.CHECKOUT:    ("🚪",  "CHECK-OUT"),
    TipoEvento.PAGO:        ("💳",  "PAGO REGISTRADO"),
    TipoEvento.CARGO_EXTRA: ("🍽",  "CARGO EXTRA"),
    TipoEvento.VUELTO:      ("💵",  "VUELTO ENTREGADO"),
    TipoEvento.RENOVACION:  ("🔄",  "RENOVACIÓN"),
    TipoEvento.RESERVACION: ("📅",  "RESERVACIÓN"),
    TipoEvento.CAJA:        ("🏦",  "MOVIMIENTO DE CAJA"),
    TipoEvento.NOTA:        ("📝",  "NOTA"),
    TipoEvento.SISTEMA:     ("⚙️",  "SISTEMA"),
}


def _hora() -> str:
    ahora = datetime.now()
    dias  = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    return f"⏰ {ahora.strftime('%H:%M')} · {dias[ahora.weekday()]} {ahora.strftime('%d/%m/%Y')}"


def _cab(tipo: TipoEvento) -> str:
    emoji, etiq = _CFG.get(tipo, ("🔔", str(tipo.value).upper()))
    return f"{emoji} <b>{etiq}</b>"


def _linea(icono: str, label: str, valor) -> str:
    if not valor and valor != 0:
        return ""
    return f"{icono} <b>{label}:</b> {valor}"


def _monto(monto_usd: float, monto_bs: float = 0, tasa: float = 0) -> str:
    partes = []
    if monto_usd and monto_usd > 0.001:
        partes.append(f"${monto_usd:,.2f}")
    if monto_bs and monto_bs > 0.001:
        partes.append(f"Bs. {monto_bs:,.2f}")
    elif monto_usd and tasa:
        partes.append(f"Bs. {monto_usd * tasa:,.2f}")
    return "  ·  ".join(partes) if partes else ""


# ══════════════════════════════════════════════════════════════════════════════
# APERTURA / CIERRE DE TURNO  (datos directos, no BitacoraEvento)
# ══════════════════════════════════════════════════════════════════════════════

def apertura_turno(
    recepcionista: str,
    caja_usd: float,
    caja_bs: float,
    tasa: float,
) -> str:
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "🔑 <b>APERTURA DE TURNO</b>",
        _linea("👤", "Recepcionista", recepcionista),
        _linea("💵", "Caja chica",    f"${caja_usd:,.2f}  ·  Bs. {caja_bs:,.2f}"),
        _linea("💱", "Tasa del día",  f"Bs. {tasa:,.2f} / USD"),
        _hora(),
    ]))


def cierre_turno(
    recepcionista: str,
    cobrado_usd: float,
    vueltos_usd: float,
    neto_usd: float,
    caja_chica_usd: float,
    diferencia_usd: float,
) -> str:
    estado_dif = (
        "✅ Cuadrado" if abs(diferencia_usd) < 0.05
        else (f"⚠️ Sobrante ${diferencia_usd:,.2f}" if diferencia_usd > 0
              else f"❌ Faltante ${abs(diferencia_usd):,.2f}")
    )
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "🔒 <b>CIERRE DE TURNO</b>",
        _linea("👤", "Recepcionista",  recepcionista),
        _linea("💰", "Cobrado",        f"${cobrado_usd:,.2f}"),
        _linea("↩️",  "Vueltos",        f"${vueltos_usd:,.2f}"),
        _linea("📊", "Neto ingresado", f"${neto_usd:,.2f}"),
        _linea("🏦", "Caja chica",     f"${caja_chica_usd:,.2f}"),
        _linea("⚖️",  "Diferencia",     estado_dif),
        _hora(),
    ]))


# ══════════════════════════════════════════════════════════════════════════════
# FORMATEADOR GENÉRICO  (para BitacoraEvento)
# ══════════════════════════════════════════════════════════════════════════════

def desde_evento(evento, tasa: float = 0) -> str:
    """
    Recibe un objeto BitacoraEvento (o dict con los mismos campos)
    y devuelve el texto HTML para Telegram.
    """
    # Soporte para dict y objeto ORM
    def _get(attr, default=""):
        if isinstance(evento, dict):
            return evento.get(attr, default)
        return getattr(evento, attr, default)

    tipo        = _get("tipo")
    habitacion  = _get("habitacion", "")
    concepto    = _get("concepto", "")
    monto_usd   = float(_get("monto_usd") or 0)
    monto_bs    = float(_get("monto_bs")  or 0)
    metodo      = _get("metodo_pago", "")
    referencia  = _get("referencia", "")
    recep       = _get("recepcionista", "")
    confirmado  = _get("confirmado", True)

    emoji, etiq = _CFG.get(tipo, ("🔔", str(tipo.value).upper() if tipo else "EVENTO"))

    lineas = [_HOTEL, _SEP, f"{emoji} <b>{etiq}</b>"]

    # CHECKIN: el concepto ya incluye "HabX $XX.XX..." — no repetir habitación
    if habitacion and tipo != TipoEvento.CHECKIN:
        lineas.append(_linea("🛏", "Habitación", f"N° {habitacion}"))

    if concepto:
        lineas.append(_linea("📋", "Detalle", concepto))

    monto_txt = _monto(monto_usd, monto_bs, tasa)
    if monto_txt:
        lineas.append(_linea("💰", "Monto", monto_txt))

    if metodo:
        lineas.append(_linea("💳", "Método", metodo))

    if referencia:
        lineas.append(_linea("🔖", "Referencia", referencia))

    if recep:
        lineas.append(_linea("👤", "Registrado por", recep))

    if not confirmado:
        lineas.append("⏳ <i>Pendiente de confirmación</i>")

    lineas.append(_hora())
    return "\n".join(filter(None, lineas))


# ══════════════════════════════════════════════════════════════════════════════
# FORMATEADORES ESPECÍFICOS  (más contexto que el genérico)
# ══════════════════════════════════════════════════════════════════════════════

def checkin(
    habitacion: str,
    nombre_huesped: str,
    noches: int,
    fecha_salida: str,
    total_usd: float,
    tasa: float,
    recepcionista: str = "",
) -> str:
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "🛎 <b>CHECK-IN</b>",
        _linea("🛏", "Habitación",  f"N° {habitacion}"),
        _linea("👤", "Huésped",     nombre_huesped),
        _linea("🌙", "Noches",      str(noches)),
        _linea("📅", "Salida est.", fecha_salida),
        _linea("💰", "Total",       _monto(total_usd, tasa=tasa)),
        _linea("🧑‍💼", "Recepción",  recepcionista) if recepcionista else "",
        _hora(),
    ]))


def checkout(
    habitacion: str,
    nombre_huesped: str,
    estado_financiero: str,
    recepcionista: str = "",
) -> str:
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "🚪 <b>CHECK-OUT</b>",
        _linea("🛏", "Habitación",  f"N° {habitacion}"),
        _linea("👤", "Huésped",     nombre_huesped),
        _linea("📊", "Balance",     estado_financiero),
        _linea("🧑‍💼", "Recepción",  recepcionista) if recepcionista else "",
        _hora(),
    ]))


def pago(
    habitacion: str,
    nombre_huesped: str,
    monto_usd: float,
    monto_bs: float,
    metodo: str,
    referencia: str = "",
    recepcionista: str = "",
    es_parcial: bool = False,
    pendiente_usd: float = 0,
) -> str:
    estado = f"⚠️ Parcial — quedan ${pendiente_usd:,.2f}" if es_parcial else "✅ Completo"
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "💳 <b>PAGO REGISTRADO</b>",
        _linea("🛏", "Habitación",  f"N° {habitacion}"),
        _linea("👤", "Huésped",     nombre_huesped),
        _linea("💰", "Monto",       _monto(monto_usd, monto_bs)),
        _linea("💳", "Método",      metodo),
        _linea("🔖", "Referencia",  referencia) if referencia else "",
        _linea("📊", "Estado",      estado),
        _linea("🧑‍💼", "Recepción",  recepcionista) if recepcionista else "",
        _hora(),
    ]))


def cargo_extra(
    habitacion: str,
    concepto: str,
    monto_usd: float,
    tasa: float,
    recepcionista: str = "",
) -> str:
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "🍽 <b>CARGO EXTRA</b>",
        _linea("🛏", "Habitación", f"N° {habitacion}"),
        _linea("📋", "Concepto",   concepto),
        _linea("💰", "Monto",      _monto(monto_usd, tasa=tasa)),
        _linea("🧑‍💼", "Recepción", recepcionista) if recepcionista else "",
        _hora(),
    ]))


def reservacion(
    nombre: str,
    tipo_hab: str,
    fecha_entrada: str,
    fecha_salida: str,
    telefono: str = "",
    estado: str = "PENDIENTE",
    origen: str = "sistema",
) -> str:
    origen_txt = "🌐 Web" if origen == "web" else "💻 Sistema"
    return "\n".join(filter(None, [
        _HOTEL, _SEP,
        "📅 <b>RESERVACIÓN</b>",
        _linea("👤", "Titular",    nombre),
        _linea("🛏", "Tipo",       tipo_hab),
        _linea("📆", "Entrada",    fecha_entrada),
        _linea("📆", "Salida",     fecha_salida),
        _linea("📞", "Teléfono",   telefono) if telefono else "",
        _linea("🔵", "Estado",     estado),
        _linea("🌐", "Origen",     origen_txt),
        _hora(),
    ]))