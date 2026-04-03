"""
Convierte eventos en mensajes HTML para Telegram.

Estructura del CHECK-IN:
  🛎 CHECK-IN  Hab[N]
  💰 $XX.XX  ⏳ Pendiente por cancelar
       ó
  💰 $XX.XX  ✅ cancelado por [método(s)]
     (Pago Móvil incluye: Bs.XXXX  Ref:0000  Tlf:04XX)
  👤 Registrado por: [usuario]
  🌙 X noche(s) · 📅 Sal. dd/mm/aaaa
  ⏰ HH:MM · día dd/mm/aaaa
"""

from datetime import datetime
from database.models import TipoEvento

_HOTEL = "🏨 <b>La Posada de Daniel C.A.</b>"
_SEP = "━━━━━━━━━━━━━━━━━━━━━"

_CFG = {
    TipoEvento.CHECKIN: ("🛎", "CHECK-IN"),
    TipoEvento.CHECKOUT: ("🚪", "CHECK-OUT"),
    TipoEvento.PAGO: ("💳", "PAGO REGISTRADO"),
    TipoEvento.CARGO_EXTRA: ("🍽", "CARGO EXTRA"),
    TipoEvento.VUELTO: ("💵", "VUELTO ENTREGADO"),
    TipoEvento.RENOVACION: ("🔄", "RENOVACIÓN"),
    TipoEvento.RESERVACION: ("📅", "RESERVACIÓN"),
    TipoEvento.CAJA: ("🏦", "MOVIMIENTO DE CAJA"),
    TipoEvento.NOTA: ("📝", "NOTA"),
    TipoEvento.SISTEMA: ("⚙️", "SISTEMA"),
}


def _hora() -> str:
    ahora = datetime.now()
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    return f"⏰ {ahora.strftime('%H:%M')} · {dias[ahora.weekday()]} {ahora.strftime('%d/%m/%Y')}"


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
# FORMATEADOR DE MÉTODOS DE PAGO  (para CHECK-IN)
# ══════════════════════════════════════════════════════════════════════════════


def _nombre_metodo(metodo) -> str:
    """Normaliza el método a string limpio."""
    if hasattr(metodo, "value"):
        return metodo.value
    return str(metodo).strip()


def _linea_metodo(p: dict) -> str:
    """
    Genera la línea de texto de un método de pago.
    Pago Móvil incluye Bs, Ref y Tlf.
    Transferencia incluye Bs y Ref.
    Zelle/Débito incluye USD y Ref.
    Efectivo muestra monto en la moneda correspondiente.
    """
    metodo = _nombre_metodo(p.get("metodo", "")).lower()
    usd = p.get("monto_usd", 0) or 0
    bs = p.get("monto_bs", 0) or 0
    ref = (p.get("referencia", "") or "").strip()
    tlf = (p.get("telefono_pm", "") or "").strip()

    if "pago móvil" in metodo or "pago movil" in metodo:
        txt = f"📱 Pago Móvil  Bs.{bs:,.2f}"
        if ref:
            txt += f"  Ref:{ref}"
        if tlf:
            txt += f"  Tlf:{tlf}"
        return txt

    if "transferencia" in metodo:
        txt = f"🏦 Transferencia  Bs.{bs:,.2f}"
        if ref:
            txt += f"  Ref:{ref}"
        return txt

    if "zelle" in metodo:
        txt = f"💸 Zelle  ${usd:,.2f}"
        if ref:
            txt += f"  Ref:{ref}"
        return txt

    if "pix" in metodo:
        txt = f"💸 Pix  ${usd:,.2f}"
        if ref:
            txt += f"  Ref:{ref}"
        return txt

    if "reais" in metodo or "real" in metodo:
        txt = f"💸 Reais  ${usd:,.2f}"
        if ref:
            txt += f"  Ref:{ref}"
        return txt

    if "efectivo $" in metodo or metodo == "efectivo $":
        return f"💵 Efectivo $  ${usd:,.2f}"

    if "efectivo bs" in metodo:
        return f"💵 Efectivo Bs  Bs.{bs:,.2f}"

    if "débito" in metodo or "debito" in metodo:
        # Tarjeta Débito: se paga en BS a nuestro banco
        txt = f"💳 Tarjeta Débito  Bs.{bs:,.2f}"
        if ref:
            txt += f"  Ref:{ref}"
        return txt

    if "saldo" in metodo:
        return f"🏧 Saldo a favor  ${usd:,.2f}"

    # Genérico
    return f"💰 {_nombre_metodo(p.get('metodo', ''))}  ${usd:,.2f}"


def _formatear_metodos(pagos: list) -> str:
    """
    Convierte lista de pagos en texto para el mensaje.
    Un método: inline. Varios métodos: uno por línea indentada.
    """
    if not pagos:
        return "—"
    lineas = [_linea_metodo(p) for p in pagos]
    if len(lineas) == 1:
        return lineas[0]
    # Múltiples métodos: cada uno en su propia línea indentada
    return "\n   " + "\n   ".join(lineas)


# ══════════════════════════════════════════════════════════════════════════════
# CHECK-IN — formateador principal
# ══════════════════════════════════════════════════════════════════════════════


def checkin_mensaje(
    habitacion: str,
    precio_usd: float,
    nombre: str,
    noches: int,
    fecha_salida: str,
    recepcionista: str,
    pagos: list,
    pendiente: bool,
    es_operativo: bool = False,
) -> str:
    """
    Genera el mensaje de Telegram para un check-in con todos sus escenarios:

    • Pago parcial:
        💰 $30.00  ✅ cancelado por
           💸 Zelle  $15.00 Ref:ZEL123
        ⏳ Pendiente por cancelar $15.00

    • pendiente=True  (omitió pago o pago parcial, sin pagos):
        💰 $30.00  ⏳ Pendiente por cancelar

    • pendiente=False (pagó completo):
        💰 $30.00  ✅ cancelado por 📱 Pago Móvil  Bs.1,100.00  Ref:8624  Tlf:04141234567
        ó con múltiples métodos:
        💰 $30.00  ✅ cancelado por
           💵 Efectivo $  $15.00
           💸 Zelle  $15.00  Ref:ABC123

    • es_operativo=True:
        💰 *OP* $20.00  ✅ cancelado por 💳 Tarjeta Débito  Bs [monto en bs]
    """
    lineas = [
        _HOTEL,
        _SEP,
        f"🛎 <b>CHECK-IN  Hab{habitacion}</b>",
    ]

    pagos_hechos = pagos if pagos else []
    total_abonado = sum(p.get("monto_usd", 0) for p in pagos_hechos)
    saldo_pendiente = precio_usd - total_abonado

    # Formatear precio según tipo
    if es_operativo:
        precio_txt = f"<b>*OP* ${precio_usd:,.2f}</b>"
    else:
        precio_txt = f"<b>${precio_usd:,.2f}</b>"

    if pagos_hechos and saldo_pendiente > 0.01:
        metodos_txt = _formatear_metodos(pagos_hechos)
        if len(pagos_hechos) == 1:
            lineas.append(f"💰 {precio_txt}  ✅ cancelado por {metodos_txt}")
        else:
            lineas.append(f"💰 {precio_txt}  ✅ cancelado por\n   {metodos_txt.strip()}")
        lineas.append(f"⏳ Pendiente por cancelar ${saldo_pendiente:,.2f}")
    elif total_abonado > precio_usd + 0.01:
        metodos_txt = _formatear_metodos(pagos_hechos)
        lineas.append(f"💰 {precio_txt}  ✅ cancelado por {metodos_txt}")
        if saldo_pendiente > 0.01:
            lineas.append(f"🔴 Pendiente por devolver ${saldo_pendiente:,.2f}")
    elif pendiente or not pagos_hechos:
        lineas.append(f"💰 {precio_txt}  ⏳ Pendiente por cancelar")
    else:
        metodos_txt = _formatear_metodos(pagos_hechos)
        if len(pagos_hechos) == 1:
            lineas.append(f"💰 {precio_txt}  ✅ cancelado por {metodos_txt}")
        else:
            lineas.append(f"💰 {precio_txt}  ✅ cancelado por\n   {metodos_txt.strip()}")

    # Huésped, recepcionista y estadía
    if nombre:
        lineas.append(_linea("👤", "Huésped", nombre))
    if recepcionista:
        lineas.append(_linea("🧑‍💼", "Registrado por", recepcionista))
    if noches > 0 and fecha_salida:
        if es_operativo:
            lineas.append(f"🕐 Salida {fecha_salida}")
        else:
            lineas.append(
                f"🌙 {noches} noche{'s' if noches != 1 else ''}  ·  📅 Sal. {fecha_salida}"
            )
    lineas.append(_hora())

    return "\n".join(filter(None, lineas))


# ══════════════════════════════════════════════════════════════════════════════
# APERTURA / CIERRE DE TURNO
# ══════════════════════════════════════════════════════════════════════════════


def apertura_turno(
    recepcionista: str,
    caja_usd: float,
    caja_bs: float,
    tasa: float,
) -> str:
    return "\n".join(
        filter(
            None,
            [
                _HOTEL,
                _SEP,
                "🔑 <b>APERTURA DE TURNO</b>",
                _linea("👤", "Recepcionista", recepcionista),
                _linea("💵", "Caja chica", f"${caja_usd:,.2f}  ·  Bs. {caja_bs:,.2f}"),
                _linea("💱", "Tasa del día", f"Bs. {tasa:,.2f} / USD"),
                _hora(),
            ],
        )
    )


def cierre_turno(
    recepcionista: str,
    cobrado_usd: float,
    vueltos_usd: float,
    neto_usd: float,
    caja_chica_usd: float,
    diferencia_usd: float,
) -> str:
    estado_dif = (
        "✅ Cuadrado"
        if abs(diferencia_usd) < 0.05
        else (
            f"⚠️ Sobrante ${diferencia_usd:,.2f}"
            if diferencia_usd > 0
            else f"❌ Faltante ${abs(diferencia_usd):,.2f}"
        )
    )
    return "\n".join(
        filter(
            None,
            [
                _HOTEL,
                _SEP,
                "🔒 <b>CIERRE DE TURNO</b>",
                _linea("👤", "Recepcionista", recepcionista),
                _linea("💰", "Cobrado", f"${cobrado_usd:,.2f}"),
                _linea("↩️", "Vueltos", f"${vueltos_usd:,.2f}"),
                _linea("📊", "Neto ingresado", f"${neto_usd:,.2f}"),
                _linea("🏦", "Caja chica", f"${caja_chica_usd:,.2f}"),
                _linea("⚖️", "Diferencia", estado_dif),
                _hora(),
            ],
        )
    )


# ══════════════════════════════════════════════════════════════════════════════
# FORMATEADOR GENÉRICO  (todos los eventos excepto CHECKIN)
# ══════════════════════════════════════════════════════════════════════════════


def desde_evento(evento, tasa: float = 0) -> str:
    """
    Recibe un BitacoraEvento (ORM o dict) y devuelve el texto HTML.
    Los eventos CHECKIN los maneja checkin_mensaje() — este formatter
    solo muestra el concepto ya construido.
    """

    def _get(attr, default=""):
        if isinstance(evento, dict):
            return evento.get(attr, default)
        return getattr(evento, attr, default)

    tipo = _get("tipo")
    habitacion = _get("habitacion", "")
    concepto = _get("concepto", "")
    monto_usd = float(_get("monto_usd") or 0)
    monto_bs = float(_get("monto_bs") or 0)
    metodo = _get("metodo_pago", "")
    referencia = _get("referencia", "")
    recep = _get("recepcionista", "")
    confirmado = _get("confirmado", True)

    emoji, etiq = _CFG.get(tipo, ("🔔", str(tipo.value).upper() if tipo else "EVENTO"))

    lineas = [_HOTEL, _SEP, f"{emoji} <b>{etiq}</b>"]

    if habitacion and tipo != TipoEvento.CHECKIN:
        lineas.append(_linea("🛏", "Habitación", f"N° {habitacion}"))

    if tipo == TipoEvento.CARGO_EXTRA:
        if concepto:
            import re
            match = re.search(r'\((?:saldo|vuelto) a favor \$[\d,]+\.\d{2}\)', concepto)
            if match:
                concepto_limpio = concepto.replace(match.group(), '').strip()
                if concepto_limpio:
                    lineas.append(_linea("📋", "Servicio", concepto_limpio))
                saldo_match = re.search(r'(saldo|vuelto) a favor \$([\d,]+\.\d{2})', match.group())
                if saldo_match:
                    tipo_origen = saldo_match.group(1)
                    saldo_valor = float(saldo_match.group(2).replace(',', ''))
                    etiqueta = "vuelto a favor" if tipo_origen == "vuelto" else "saldo a favor"
                    lineas.append(_linea("💳", f"Cubierto con {etiqueta}", f"${saldo_valor:,.2f}"))
                    if not confirmado:
                        restante = monto_usd - saldo_valor
                        if restante > 0.01:
                            lineas.append(f"⏳ <i>Pendiente por cancelar: ${restante:,.2f}</i>")
                    else:
                        lineas.append("✅ <b>Cancelado</b>")
            else:
                lineas.append(_linea("📋", "Servicio", concepto))
                if confirmado:
                    lineas.append("✅ <b>Cancelado</b>")
    elif concepto:
        lineas.append(_linea("📋", "Detalle", concepto))

    monto_txt = _monto(monto_usd, monto_bs, tasa)
    if monto_txt:
        lineas.append(_linea("💰", "Monto", monto_txt))

    if metodo and tipo != TipoEvento.CARGO_EXTRA:
        lineas.append(_linea("💳", "Método", metodo))

    if referencia:
        lineas.append(_linea("🔖", "Referencia", referencia))

    if recep:
        lineas.append(_linea("👤", "Registrado por", recep))

    if not confirmado and tipo != TipoEvento.CARGO_EXTRA:
        lineas.append("⏳ <i>Pendiente por cancelar</i>")

    lineas.append(_hora())
    return "\n".join(filter(None, lineas))


# ══════════════════════════════════════════════════════════════════════════════
# OTROS FORMATEADORES ESPECÍFICOS
# ══════════════════════════════════════════════════════════════════════════════


def checkout(
    habitacion: str,
    nombre_huesped: str,
    estado_financiero: str,
    recepcionista: str = "",
) -> str:
    return "\n".join(
        filter(
            None,
            [
                _HOTEL,
                _SEP,
                "🚪 <b>CHECK-OUT</b>",
                _linea("🛏", "Habitación", f"N° {habitacion}"),
                _linea("👤", "Huésped", nombre_huesped),
                _linea("📊", "Balance", estado_financiero),
                _linea("🧑‍💼", "Recepción", recepcionista) if recepcionista else "",
                _hora(),
            ],
        )
    )


def cargo_extra(
    habitacion: str,
    concepto: str,
    monto_usd: float,
    tasa: float,
    recepcionista: str = "",
    confirmado: bool = False,
) -> str:
    estado = "✅ Cancelado" if confirmado else "⏳ Pendiente por cancelar"
    return "\n".join(
        filter(
            None,
            [
                _HOTEL,
                _SEP,
                "🍽 <b>CARGO EXTRA</b>",
                _linea("🛏", "Habitación", f"N° {habitacion}"),
                _linea("📋", "Concepto", concepto),
                _linea("💰", "Monto", _monto(monto_usd, tasa=tasa)),
                estado,
                _linea("🧑‍💼", "Recepción", recepcionista) if recepcionista else "",
                _hora(),
            ],
        )
    )


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
    return "\n".join(
        filter(
            None,
            [
                _HOTEL,
                _SEP,
                "📅 <b>RESERVACIÓN</b>",
                _linea("👤", "Titular", nombre),
                _linea("🛏", "Tipo", tipo_hab),
                _linea("📆", "Entrada", fecha_entrada),
                _linea("📆", "Salida", fecha_salida),
                _linea("📞", "Teléfono", telefono) if telefono else "",
                _linea("🔵", "Estado", estado),
                _linea("🌐", "Origen", origen_txt),
                _hora(),
            ],
        )
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGO EN RESPUESTA A CHECK-IN PENDIENTE
# ══════════════════════════════════════════════════════════════════════════════


def pago_respuesta(
    habitacion: str,
    nombre: str,
    monto_pagado: float,
    pagos: list,
    saldo_pendiente: float,
    recepcionista: str,
    es_respuesta: bool = False,
    lineas_detalle: list = None,
    precio_habitacion: float = 0,
    es_operativo: bool = False,
    fecha_salida: str = "",
) -> str:
    """
    Mensaje de confirmación de pago que responde al mensaje original del check-in.

    Si es_respuesta=True, el mensaje será más corto ya que Telegram lo mostrará
    agrupado con el mensaje al que responde.

    lineas_detalle: lista de dicts con 'concepto' y 'monto' para mostrar desglose.
    precio_habitacion: precio total de la habitación para calcular sobrepago.
    es_operativo: si es true, muestra mensaje de habitación operativa.
    """
    lineas_detalle = lineas_detalle or []
    precio_real = precio_habitacion if precio_habitacion > 0 else monto_pagado
    sobrepago = -saldo_pendiente if saldo_pendiente < -0.01 else 0

    # Formatear precio según tipo
    if es_operativo:
        precio_txt = f"<b>*OP* ${monto_pagado:,.2f}</b>"
    else:
        precio_txt = f"<b>${monto_pagado:,.2f}</b>"

    if es_respuesta:
        lineas = []
        if pagos:
            metodos_txt = _formatear_metodos(pagos)
            lineas.append(f"💳 <b>PAGO REGISTRADO</b>")
            lineas.append(f"🛏 <b>Hab{habitacion}</b>")

            if lineas_detalle:
                lineas.append("📋 <b>Detalle:</b>")
                for l in lineas_detalle:
                    concepto = l.get("concepto", "Cobro")
                    monto = l.get("monto", 0)
                    lineas.append(f"   • {concepto}: ${monto:,.2f}")
                lineas.append(f"───────────────────")
                lineas.append(f"💰 <b>TOTAL: ${monto_pagado:,.2f}</b>")
            elif sobrepago > 0.01:
                lineas.append(f"💰 Habitación: ${precio_real:,.2f}")
                lineas.append(f"✅ Cancelado: ${monto_pagado:,.2f}")
                lineas.append(f"💳 {metodos_txt}")
                lineas.append(f"🔴 <b>Pendiente por devolver: ${sobrepago:,.2f}</b>")
            elif saldo_pendiente > 0.01:
                lineas.append(f"💰 Habitación: ${precio_real:,.2f}")
                lineas.append(f"✅ Cancelado: ${monto_pagado:,.2f}")
                lineas.append(f"💳 {metodos_txt}")
                lineas.append(f"⏳ Pendiente: ${saldo_pendiente:,.2f}")
            else:
                lineas.append(f"💰 ${monto_pagado:,.2f}")
                lineas.append(f"💳 {metodos_txt}")
                lineas.append("✅ <b>SALDADA</b>")

            if nombre:
                lineas.append(_linea("👤", "Huésped", nombre))
            lineas.append(_linea("🧑‍💼", "Recibido por", recepcionista))
        else:
            lineas.append(f"💳 <b>PAGO REGISTRADO</b> — Hab{habitacion}")
            lineas.append(f"💰 ${monto_pagado:,.2f}")
        return "\n".join(filter(None, lineas))
    else:
        return checkin_mensaje(
            habitacion=habitacion,
            precio_usd=precio_real,
            nombre=nombre,
            noches=1 if es_operativo else 0,
            fecha_salida=fecha_salida,
            recepcionista=recepcionista,
            pagos=pagos,
            pendiente=saldo_pendiente > 0.01,
            es_operativo=es_operativo,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGO A CUENTA EXISTENTE (DEUDA TURNO ANTERIOR / ABONO)
# ══════════════════════════════════════════════════════════════════════════════


def pago_cuenta(
    habitacion: str,
    monto_cuenta: float,
    monto_abonado: float,
    pagos: list,
    saldo_pendiente: float,
    recepcionista: str,
    nombre: str = "",
    cargos_extras: list = None,
    es_abono: bool = False,
) -> str:
    """
    Mensaje para pagos a cuentas existentes (deudas de turnos anteriores, abonos).

    Args:
        habitacion: Número de habitación
        monto_cuenta: Monto total de la cuenta pendiente
        monto_abonado: Monto que se está pagando ahora
        pagos: Lista de métodos de pago usados
        saldo_pendiente: Saldo restante después del pago
        recepcionista: Nombre del recepcionista
        nombre: Nombre del huésped (opcional)
        cargos_extras: Lista de dicts con 'concepto' y 'monto' de cargos extras
        es_abono: True si es un abono parcial, False si es cancelación completa
    """
    lineas = [_HOTEL, _SEP]
    metodos_txt = _formatear_metodos(pagos) if pagos else "—"
    saldo_negativo = saldo_pendiente < -0.01
    sobrepago = -saldo_pendiente if saldo_negativo else 0

    if es_abono:
        lineas.append(f"💳 <b>PAGO REGISTRADO</b>")
        lineas.append(f"🛏 <b>Hab{habitacion}</b>")
        lineas.append(f"📋 <b>Detalle:</b>")
        lineas.append(f"   Abono ${monto_abonado:,.2f} a su cuenta")
        lineas.append(f"   Pendiente: ${monto_cuenta:,.2f}")
        if cargos_extras:
            for c in cargos_extras:
                lineas.append(f"   + {c.get('concepto', 'Servicio')}: ${c.get('monto', 0):,.2f}")
        lineas.append(f"───────────────────")
        lineas.append(f"✅ Cancelado: ${monto_abonado:,.2f}")
        lineas.append(f"💳 {metodos_txt}")
        if saldo_negativo:
            lineas.append(f"🔴 <b>Pendiente por devolver: ${sobrepago:,.2f}</b>")
        else:
            lineas.append(f"⏳ Pendiente por cancelar: ${saldo_pendiente:,.2f}")
    else:
        lineas.append(f"💳 <b>PAGO REGISTRADO</b>")
        lineas.append(f"🛏 <b>Hab{habitacion}</b>")
        lineas.append(f"📋 <b>Detalle:</b>")
        lineas.append(f"   Canceló cuenta pendiente: ${monto_cuenta:,.2f}")
        if cargos_extras:
            for c in cargos_extras:
                lineas.append(f"   + {c.get('concepto', 'Servicio')}: ${c.get('monto', 0):,.2f}")
            total_con_extras = monto_cuenta + sum(c.get('monto', 0) for c in cargos_extras)
            lineas.append(f"───────────────────")
            lineas.append(f"✅ Total cancelado: ${total_con_extras:,.2f}")
        else:
            lineas.append(f"───────────────────")
            lineas.append(f"✅ Total cancelado: ${monto_cuenta:,.2f}")
        lineas.append(f"💳 {metodos_txt}")
        if saldo_negativo:
            lineas.append(f"🔴 <b>Pendiente por devolver: ${sobrepago:,.2f}</b>")

    if nombre:
        lineas.append(_linea("👤", "Huésped", nombre))
    lineas.append(_linea("🧑‍💼", "Recibido por", recepcionista))
    lineas.append(_hora())

    return "\n".join(filter(None, lineas))


# ══════════════════════════════════════════════════════════════════════════════
# CHECK-IN GRUPAL — formateador para grupos de habitaciones
# ══════════════════════════════════════════════════════════════════════════════


def checkin_grupal_mensaje(
    nombre_grupo: str,
    habitaciones: list,
    huesped_principal: str,
    total_grupo: float,
    noches: int,
    fecha_salida: str,
    recepcionista: str,
    pagos: list = None,
    pendiente: bool = False,
    tasa: float = 0,
) -> str:
    """
    Genera el mensaje de Telegram para un check-in grupal.
    Sigue la misma lógica que checkin_mensaje:
    
    • Pago parcial:
        💰 $60.00  ✅ cancelado por
           💸 Zelle  $30.00
        ⏳ Pendiente por cancelar $30.00

    • pendiente=True (omitió pago o pago parcial):
        💰 $60.00  ⏳ Pendiente por cancelar

    • Pagado completo:
        💰 $60.00  ✅ cancelado por 📱 Pago Móvil  Bs.2,200.00
    """
    lineas = [
        _HOTEL,
        _SEP,
        f"🛎 <b>CHECK-IN GRUPO</b>",
        f"📛 {nombre_grupo}",
    ]
    
    # Habitaciones primero
    hab_numeros = ", ".join([str(h.get("numero", "")) for h in habitaciones])
    lineas.append(_linea("🏠", "Habitaciones", hab_numeros))
    
    pagos_hechos = pagos if pagos else []
    total_abonado = sum(p.get("monto_usd", 0) for p in pagos_hechos)
    saldo_pendiente = total_grupo - total_abonado
    
    precio_txt = f"<b>${total_grupo:,.2f}</b>"
    
    if pagos_hechos and saldo_pendiente > 0.01:
        metodos_txt = _formatear_metodos(pagos_hechos)
        lineas.append(f"💰 {precio_txt}  ✅ cancelado por\n   {metodos_txt.strip()}")
        lineas.append(f"⏳ Pendiente por cancelar ${saldo_pendiente:,.2f}")
    elif total_abonado > total_grupo + 0.01:
        metodos_txt = _formatear_metodos(pagos_hechos)
        lineas.append(f"💰 {precio_txt}  ✅ cancelado por\n   {metodos_txt.strip()}")
        if saldo_pendiente > 0.01:
            lineas.append(f"🔴 Pendiente por devolver ${abs(saldo_pendiente):,.2f}")
    elif pendiente or not pagos_hechos:
        lineas.append(f"💰 {precio_txt}  ⏳ Pendiente por cancelar")
    else:
        metodos_txt = _formatear_metodos(pagos_hechos)
        lineas.append(f"💰 {precio_txt}  ✅ cancelado por\n   {metodos_txt.strip()}")
    
    # Huésped principal después de los pagos
    if huesped_principal:
        lineas.append(_linea("👥", "Huésped principal", huesped_principal))
    
    if noches > 0 and fecha_salida:
        lineas.append(f"🌙 {noches} noche{'s' if noches != 1 else ''}  ·  📅 Sal. {fecha_salida}")
    
    if recepcionista:
        lineas.append(_linea("🧑‍💼", "Registrado por", recepcionista))
    
    lineas.append(_hora())

    return "\n".join(filter(None, lineas))
