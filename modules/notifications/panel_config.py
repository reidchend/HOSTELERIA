# modules/notifications/panel_config.py
"""
Panel de configuración de Telegram para embeber en la pantalla de administración.
Se añade como una nueva Tab en PantallaGestionCaja.

Permite:
  · Ingresar / actualizar Bot Token y Chat ID.
  · Enviar mensaje de prueba para verificar la conexión.
  · Ver el estado de la cola de pendientes.
"""

import flet as ft
from database.connection import SesionLocal
from database.models import Configuracion


def construir_panel_telegram(pagina: ft.Page) -> ft.Control:
    """
    Devuelve un ft.Column listo para usarse como contenido de un Tab.
    """

    # ── Leer valores actuales desde BD ───────────────────────────────────────
    def _leer_config():
        sesion = SesionLocal()
        try:
            def _v(clave):
                c = sesion.query(Configuracion).filter(
                    Configuracion.clave == clave
                ).first()
                return (c.valor or "").strip() if c else ""
            return _v("telegram_bot_token"), _v("telegram_chat_id")
        finally:
            sesion.close()

    token_actual, chat_id_actual = _leer_config()

    # ── Campos ────────────────────────────────────────────────────────────────
    tf_token = ft.TextField(
        label="Bot Token",
        value=token_actual,
        password=True,
        can_reveal_password=True,
        hint_text="1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        expand=True,
    )
    tf_chat = ft.TextField(
        label="Chat ID  (grupo, canal o usuario)",
        value=chat_id_actual,
        hint_text="-1001234567890",
        expand=True,
    )
    txt_estado = ft.Text("", size=12)
    txt_cola   = ft.Text("", size=11, color=ft.Colors.GREY_600)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _guardar_en_bd(token: str, chat_id: str):
        sesion = SesionLocal()
        try:
            for clave, valor, desc in [
                ("telegram_bot_token", token,
                 "Token del bot de Telegram para notificaciones"),
                ("telegram_chat_id",   chat_id,
                 "Chat ID del grupo/canal de Telegram"),
            ]:
                c = sesion.query(Configuracion).filter(
                    Configuracion.clave == clave
                ).first()
                if c:
                    c.valor = valor
                else:
                    sesion.add(Configuracion(
                        clave=clave, valor=valor, descripcion=desc
                    ))
            sesion.commit()
        finally:
            sesion.close()

    def _contar_cola() -> int:
        """
        Lee el conteo desde telegram_queue.db (archivo separado del dispatcher).
        """
        try:
            from modules.notifications.dispatcher import _conectar, _asegurar_tabla
            _asegurar_tabla()
            con = _conectar()
            res = con.execute("SELECT COUNT(*) FROM cola WHERE proximo_en <= ?",
                              (__import__("time").time(),)).fetchone()
            con.close()
            return res[0] if res else 0
        except Exception:
            return 0

    def _actualizar_estado_cola():
        n = _contar_cola()
        if n == 0:
            txt_cola.value = "✅ Cola vacía — todos los mensajes enviados."
            txt_cola.color = ft.Colors.GREEN_700
        else:
            txt_cola.value = (
                f"⏳ {n} mensaje(s) pendiente(s) en cola "
                f"(se reenviarán automáticamente)."
            )
            txt_cola.color = ft.Colors.ORANGE_700
        try:
            txt_cola.update()
        except Exception:
            pass

    # ── Acciones ──────────────────────────────────────────────────────────────
    def guardar(_):
        token   = tf_token.value.strip()
        chat_id = tf_chat.value.strip()
        if not token or not chat_id:
            txt_estado.value = "⚠️ Completa ambos campos antes de guardar."
            txt_estado.color = ft.Colors.ORANGE_700
            txt_estado.update()
            return
        _guardar_en_bd(token, chat_id)
        txt_estado.value = "✅ Configuración guardada correctamente."
        txt_estado.color = ft.Colors.GREEN_700
        txt_estado.update()

    def probar(_):
        token   = tf_token.value.strip()
        chat_id = tf_chat.value.strip()
        if not token or not chat_id:
            txt_estado.value = "⚠️ Ingresa el token y el chat ID primero."
            txt_estado.color = ft.Colors.ORANGE_700
            txt_estado.update()
            return
        txt_estado.value = "⏳ Enviando mensaje de prueba..."
        txt_estado.color = ft.Colors.BLUE_700
        txt_estado.update()
        pagina.update()

        from modules.notifications.telegram import verificar_conexion
        ok, error = verificar_conexion(token, chat_id)
        if ok:
            txt_estado.value = "✅ Conexión exitosa — revisa el grupo/canal."
            txt_estado.color = ft.Colors.GREEN_700
        else:
            txt_estado.value = f"❌ Error: {error}"
            txt_estado.color = ft.Colors.RED_700
        txt_estado.update()

    def refrescar_cola(_):
        _actualizar_estado_cola()

    # ── Instrucciones ─────────────────────────────────────────────────────────
    instrucciones = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.BLUE_700, size=14),
                ft.Text("Cómo configurar", size=12, weight="bold",
                        color=ft.Colors.BLUE_700),
            ], spacing=6),
            ft.Text(
                "1. Abre Telegram y busca @BotFather.\n"
                "2. Escribe /newbot, elige nombre y usuario, copia el token.\n"
                "3. Agrega el bot al grupo/canal como administrador.\n"
                "4. Obtén el Chat ID usando @userinfobot o la API.\n"
                "5. Pega ambos valores aquí y haz clic en Probar.",
                size=11, color=ft.Colors.BLUE_GREY_700,
            ),
        ], spacing=6),
        bgcolor=ft.Colors.BLUE_50,
        border=ft.border.all(1, ft.Colors.BLUE_200),
        border_radius=10,
        padding=14,
    )

    # ── Nota sobre fuentes de configuración ──────────────────────────────────
    nota_env = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.INFO, color=ft.Colors.GREY_500, size=13),
            ft.Text(
                "Los valores guardados aquí tienen prioridad sobre el archivo .env.",
                size=10, color=ft.Colors.GREY_500, italic=True,
            ),
        ], spacing=6),
    )

    # Inicializar estado de la cola al construir el panel
    _actualizar_estado_cola()

    return ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.SEND, color=ft.Colors.BLUE_700, size=16),
            ft.Text("Notificaciones por Telegram", size=14, weight="bold",
                    color=ft.Colors.BLUE_GREY_900),
        ], spacing=8),
        ft.Text(
            "Cada acción del sistema (check-in, pagos, apertura/cierre de turno, etc.) "
            "se enviará automáticamente al grupo configurado.",
            size=12, color=ft.Colors.GREY_600,
        ),
        instrucciones,
        ft.Row([tf_token], spacing=10),
        ft.Row([tf_chat], spacing=10),
        nota_env,
        txt_estado,
        ft.Row([
            ft.ElevatedButton(
                "Guardar configuración",
                icon=ft.Icons.SAVE,
                bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE,
                on_click=guardar,
            ),
            ft.ElevatedButton(
                "Enviar mensaje de prueba",
                icon=ft.Icons.SEND,
                bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,
                on_click=probar,
            ),
        ], spacing=12),
        ft.Divider(height=14),
        ft.Row([
            ft.Icon(ft.Icons.QUEUE, color=ft.Colors.GREY_600, size=14),
            ft.Text("Estado de la cola de reintentos", size=12,
                    weight="bold", color=ft.Colors.GREY_700),
            ft.Container(expand=True),
            ft.TextButton(
                "Actualizar",
                icon=ft.Icons.REFRESH,
                on_click=refrescar_cola,
            ),
        ], spacing=6),
        txt_cola,
    ], spacing=12, scroll=ft.ScrollMode.AUTO)