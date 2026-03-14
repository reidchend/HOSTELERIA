# modules/finance/panel_pendientes.py
"""
Modal de pendientes financieros con soporte para dar de baja cuentas.

Cada item lleva los IDs necesarios para ejecutar la baja:
  fuente="folio"   → estadia_id  → anula FolioLineas sin cancelar
  fuente="credito" → huesped_id  → pone credito_usd = 0
"""

import flet as ft
from decimal import Decimal
from datetime import datetime
from database.connection import SesionLocal
from database.models import Huesped, Estadia, FolioLinea
from sqlalchemy.orm import selectinload
from utils.calculos_financieros import a_bs


# ── Punto de entrada ─────────────────────────────────────────────────────────

def abrir_modal_pendientes(pagina: ft.Page, estado_app: dict):
    tasa  = estado_app.get("tasa_cambio", 1.0)
    datos = _cargar_datos()

    # El modal se reconstruye al dar de baja — guardamos referencia
    dlg_ref = [None]

    def reabrir(_=None):
        if dlg_ref[0]:
            pagina.close(dlg_ref[0])
        abrir_modal_pendientes(pagina, estado_app)

    def cerrar(_=None):
        pagina.close(dlg_ref[0])

    # ── Secciones ─────────────────────────────────────────────────────────────
    def col_items(lista, color, bg):
        if not lista:
            return ft.Column([
                ft.Text("Ninguna", size=12, color=ft.Colors.GREY_400,
                        italic=True)
            ])
        return ft.Column(
            controls=[_fila(item, tasa, color, bg, pagina, reabrir)
                      for item in lista],
            spacing=6,
        )

    total_v = sum(i["monto_usd"] for i in datos["vueltos"])
    total_d = sum(i["monto_usd"] for i in datos["deudas"])

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Icon(ft.Icons.PENDING_ACTIONS, color=ft.Colors.BLUE_700, size=20),
            ft.Text("Pendientes Financieros", size=16, weight="bold",
                    color=ft.Colors.BLUE_GREY_900, expand=True),
        ], spacing=8),
        content=ft.Container(
            width=500,
            height=540,
            content=ft.Column([

                # ── Vueltos ───────────────────────────────────────────────────
                _encabezado(
                    f"Vueltos por entregar  ({len(datos['vueltos'])})",
                    f"Total: ${total_v:,.2f}",
                    ft.Icons.CURRENCY_EXCHANGE,
                    ft.Colors.ORANGE_700,
                    ft.Colors.ORANGE_50,
                    ft.Colors.ORANGE_200,
                ),
                col_items(datos["vueltos"], ft.Colors.ORANGE_700, ft.Colors.ORANGE_50),

                ft.Divider(height=14),

                # ── Deudas ────────────────────────────────────────────────────
                _encabezado(
                    f"Cuentas por cobrar  ({len(datos['deudas'])})",
                    f"Total: ${total_d:,.2f}",
                    ft.Icons.MONEY_OFF,
                    ft.Colors.RED_700,
                    ft.Colors.RED_50,
                    ft.Colors.RED_200,
                ),
                col_items(datos["deudas"], ft.Colors.RED_700, ft.Colors.RED_50),

            ], spacing=8, scroll=ft.ScrollMode.AUTO),
        ),
        actions=[
            ft.TextButton("Cerrar", on_click=cerrar),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    dlg_ref[0] = dlg
    pagina.open(dlg)


# ── Widgets ───────────────────────────────────────────────────────────────────

def _encabezado(titulo, total_txt, icono, color, bg, border_color):
    return ft.Container(
        content=ft.Row([
            ft.Icon(icono, color=color, size=14),
            ft.Text(titulo, size=11, weight="bold", color=color),
            ft.Container(expand=True),
            ft.Text(total_txt, size=11, color=color),
        ], spacing=6),
        bgcolor=bg,
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        border_radius=8,
        border=ft.border.all(1, border_color),
    )


def _fila(item: dict, tasa: float, color, bg,
          pagina: ft.Page, al_dar_baja) -> ft.Container:

    # Identificador visual
    if item["activo"]:
        id_widget = ft.Row([
            ft.Container(
                content=ft.Text(
                    f"Hab. {item['habitacion']}",
                    size=10, weight="bold", color=ft.Colors.WHITE,
                ),
                bgcolor=color, border_radius=5,
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
            ),
            ft.Text(
                item["nombre"],
                size=12, color=ft.Colors.GREY_800,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ], spacing=8)
    else:
        id_widget = ft.Row([
            ft.Icon(ft.Icons.PERSON_OFF, size=14, color=ft.Colors.GREY_500),
            ft.Text(
                item["nombre"], size=12,
                color=ft.Colors.GREY_600,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True, italic=True,
            ),
        ], spacing=6)

    monto_col = ft.Column([
        ft.Text(f"${item['monto_usd']:,.2f}", size=13,
                weight="bold", color=color,
                text_align=ft.TextAlign.RIGHT),
        ft.Text(f"Bs. {a_bs(item['monto_usd'], tasa):,.2f}",
                size=10, color=ft.Colors.GREY_500,
                text_align=ft.TextAlign.RIGHT),
    ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END)

    btn_baja = ft.IconButton(
        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
        icon_color=ft.Colors.GREY_400,
        icon_size=18,
        tooltip="Dar de baja esta cuenta",
        on_click=lambda _, i=item: _confirmar_baja(i, pagina, al_dar_baja),
    )

    return ft.Container(
        content=ft.Row([
            ft.Container(content=id_widget, expand=True),
            monto_col,
            btn_baja,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        bgcolor=bg,
        padding=ft.padding.symmetric(horizontal=12, vertical=10),
        border_radius=8,
        border=ft.border.all(1, ft.Colors.with_opacity(0.2, color)),
    )


def _confirmar_baja(item: dict, pagina: ft.Page, al_confirmar):
    """Diálogo de confirmación antes de dar de baja."""
    if item["activo"]:
        desc = (f"Hab. {item['habitacion']} — {item['nombre']}\n"
                f"Deuda en folio: ${item['monto_usd']:,.2f}\n\n"
                f"Se marcarán todas las líneas pendientes como canceladas "
                f"sin registrar pago.")
    else:
        tipo = "vuelto" if item.get("es_vuelto") else "deuda"
        desc = (f"{item['nombre']}\n"
                f"{'Vuelto' if tipo == 'vuelto' else 'Deuda'}: "
                f"${item['monto_usd']:,.2f}\n\n"
                f"Se eliminará el saldo del perfil del huésped.")

    tf_motivo = ft.TextField(
        label="Motivo de la baja (opcional)",
        hint_text="Ej: condonado, incobrable, error de registro...",
        multiline=True, min_lines=2,
    )

    def ejecutar(_):
        motivo = tf_motivo.value.strip() or "Sin motivo especificado"
        pagina.close(dlg_conf)
        _ejecutar_baja(item, motivo, pagina, al_confirmar)

    dlg_conf = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED,
                    color=ft.Colors.ORANGE_700, size=20),
            ft.Text("Confirmar baja de cuenta", size=15, weight="bold"),
        ], spacing=8),
        content=ft.Container(
            width=400,
            content=ft.Column([
                ft.Text(desc, size=12, color=ft.Colors.GREY_700),
                ft.Divider(height=10),
                tf_motivo,
            ], spacing=10, tight=True),
        ),
        actions=[
            ft.TextButton("Cancelar",
                          on_click=lambda _: pagina.close(dlg_conf)),
            ft.ElevatedButton(
                "Dar de baja",
                bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE,
                icon=ft.Icons.DELETE_OUTLINE,
                on_click=ejecutar,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    pagina.open(dlg_conf)


def _ejecutar_baja(item: dict, motivo: str, pagina: ft.Page, al_completar):
    """Aplica la baja en la BD según la fuente del item."""
    sesion = SesionLocal()
    try:
        if item["fuente"] == "folio":
            # Cancelar todas las FolioLineas pendientes de la estadía
            est = sesion.get(Estadia, item["estadia_id"])
            if est:
                canceladas = 0
                for linea in est.folio_lineas:
                    if not linea.cancelada:
                        linea.cancelada = True
                        canceladas += 1
                # Registrar en bitácora si hay turno activo
                try:
                    from modules.finance.bitacora import registrar
                    from database.models import TipoEvento
                    registrar(
                        sesion      = sesion,
                        pagina      = pagina,
                        tipo        = TipoEvento.AJUSTE,
                        habitacion  = item.get("habitacion", ""),
                        concepto    = (f"Baja de deuda — {item['nombre']} "
                                       f"${item['monto_usd']:,.2f} · {motivo}"),
                        monto_usd   = item["monto_usd"],
                        confirmado  = True,
                    )
                except Exception:
                    pass

        else:
            # Limpiar credito_usd del perfil
            h = sesion.get(Huesped, item["huesped_id"])
            if h:
                h.credito_usd = Decimal("0")
                try:
                    from modules.finance.bitacora import registrar
                    from database.models import TipoEvento
                    registrar(
                        sesion     = sesion,
                        pagina     = pagina,
                        tipo       = TipoEvento.AJUSTE,
                        concepto   = (f"Baja de {'vuelto' if item.get('es_vuelto') else 'deuda'} "
                                      f"— {item['nombre']} "
                                      f"${item['monto_usd']:,.2f} · {motivo}"),
                        monto_usd  = item["monto_usd"],
                        confirmado = True,
                    )
                except Exception:
                    pass

        sesion.commit()
        pagina.open(ft.SnackBar(
            ft.Text(f"Cuenta dada de baja: {item['nombre']}"),
            bgcolor=ft.Colors.GREEN_700,
        ))
        al_completar()

    except Exception as e:
        sesion.rollback()
        pagina.open(ft.SnackBar(
            ft.Text(f"Error: {e}"), bgcolor=ft.Colors.RED_700,
        ))
    finally:
        sesion.close()


# ── Carga de datos ────────────────────────────────────────────────────────────

def _cargar_datos() -> dict:
    sesion = SesionLocal()
    try:
        estadias = (
            sesion.query(Estadia)
            .options(
                selectinload(Estadia.huespedes),
                selectinload(Estadia.habitacion),
                selectinload(Estadia.folio_lineas),
            )
            .filter(Estadia.activa == True)
            .all()
        )

        hab_por_huesped = {}
        for est in estadias:
            for h in est.huespedes:
                if est.habitacion:
                    hab_por_huesped[h.id] = est.habitacion.numero

        vueltos    = []
        deudas     = []
        ids_vistos = set()

        # ── Fuente 1: FolioLineas pendientes en estadías activas ─────────────
        for est in estadias:
            pendientes = [l for l in est.folio_lineas if not l.cancelada]
            total = sum(float(l.total_usd) for l in pendientes)
            if total < 0.01:
                continue
            titular = est.huespedes[0] if est.huespedes else None
            deudas.append({
                "nombre":     titular.nombre_completo if titular else "Huésped",
                "habitacion": est.habitacion.numero if est.habitacion else "?",
                "monto_usd":  total,
                "activo":     True,
                "fuente":     "folio",
                "estadia_id": est.id,
                "huesped_id": titular.id if titular else None,
                "es_vuelto":  False,
            })
            if titular:
                ids_vistos.add(titular.id)

        # ── Fuente 2: credito_usd del perfil ──────────────────────────────────
        huespedes = (
            sesion.query(Huesped)
            .filter(
                (Huesped.credito_usd > Decimal("0.01")) |
                (Huesped.credito_usd < Decimal("-0.01"))
            )
            .all()
        )

        for h in huespedes:
            monto  = float(h.credito_usd or 0)
            hab    = hab_por_huesped.get(h.id)
            activo = hab is not None

            item_base = {
                "nombre":     h.nombre_completo,
                "habitacion": hab,
                "activo":     activo,
                "fuente":     "credito",
                "huesped_id": h.id,
                "estadia_id": None,
            }

            if monto > 0.01:
                vueltos.append({**item_base,
                                "monto_usd": monto,
                                "es_vuelto": True})
            elif monto < -0.01 and h.id not in ids_vistos:
                deudas.append({**item_base,
                               "monto_usd": abs(monto),
                               "es_vuelto": False})

        vueltos.sort(key=lambda x: (not x["activo"], -x["monto_usd"]))
        deudas.sort(key=lambda x:  (not x["activo"], -x["monto_usd"]))
        return {"vueltos": vueltos, "deudas": deudas}

    except Exception as e:
        print(f"Error cargando pendientes: {e}")
        return {"vueltos": [], "deudas": []}
    finally:
        sesion.close()