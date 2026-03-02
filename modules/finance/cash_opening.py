import flet as ft
from datetime import datetime  # <--- CORRECCIÓN 1: Importación faltante
from database.connection import SessionLocal
from database.models import CashDrawer, Configuration, Shift

class CashOpeningDialog:
    def __init__(self, page, user, on_complete):
        self.page = page
        self.user = user
        self.on_complete = on_complete
        
        # Cargar datos actuales de la DB
        db = SessionLocal()
        try:
            self.caja = db.query(CashDrawer).first()
            tasa_cfg = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            self.current_tasa = float(tasa_cfg.value) if tasa_cfg else 0.0
        finally:
            db.close()

        # Fields (Asegúrate de usar main_balance o petty_cash según tu lógica)
        # Usamos petty_cash ya que es el fondo para vueltos que se valida al abrir
        self.usd_field = ft.TextField(
            label="Efectivo USD en Caja", 
            value=f"{self.caja.petty_cash_usd:.2f}" if self.caja else "0.00", 
            prefix_text="$ ", expand=True
        )
        self.bs_field = ft.TextField(
            label="Efectivo Bs en Caja", 
            value=f"{self.caja.petty_cash_bs:.2f}" if self.caja else "0.00", 
            prefix_text="Bs ", expand=True
        )
        self.tasa_field = ft.TextField(
            label="Tasa de Cambio Hoy", 
            value=f"{self.current_tasa:.2f}", 
            expand=True
        )

    def confirm_opening(self, _):
        db = SessionLocal()
        try:
            usd_fisico = float(self.usd_field.value)
            bs_fisico = float(self.bs_field.value)
            tasa_ingresada = float(self.tasa_field.value)

            # 1. Crear el nuevo turno
            nuevo_turno = Shift(
                user_id=self.user['id'],
                initial_usd=usd_fisico,
                initial_bs=bs_fisico,
                initial_exchange_rate=tasa_ingresada,
                is_active=True,
                start_time=datetime.now()
            )
            db.add(nuevo_turno)
            
            # 2. Actualizar la tasa en la configuración global
            tasa_cfg = db.query(Configuration).filter(Configuration.key == "exchange_rate").first()
            if tasa_cfg:
                tasa_cfg.value = str(tasa_ingresada)
            
            # 3. Sincronizar la Caja Física (CashDrawer)
            caja_db = db.query(CashDrawer).first()
            if caja_db:
                caja_db.petty_cash_usd = usd_fisico
                caja_db.petty_cash_bs = bs_fisico
                # Nota: Verifica si tu modelo usa 'last_update' o 'last_updated'
                # Según tu log de SQLAlchemy parece ser 'last_update'
                if hasattr(caja_db, 'last_update'):
                    caja_db.last_update = datetime.now()
            
            db.commit()
            
            # Guardamos el ID del turno en la sesión
            self.page.session.set("current_shift_id", nuevo_turno.id)
            
            # Cerrar diálogo
            self.page.close(self.dialog)
            
            # Ejecutar callback de éxito
            self.on_complete(tasa_ingresada)
            
            # CORRECCIÓN 2: Nueva forma de mostrar SnackBar en Flet
            self.page.open(ft.SnackBar(ft.Text("Turno abierto y caja sincronizada"), bgcolor="green"))
            
        except ValueError:
            self.page.open(ft.SnackBar(ft.Text("Error: Ingrese montos numéricos válidos"), bgcolor="red"))
        except Exception as e:
            db.rollback()
            # CORRECCIÓN 3: Nueva forma de mostrar SnackBar en Flet
            self.page.open(ft.SnackBar(ft.Text(f"Error al abrir turno: {e}"), bgcolor="red"))
        finally:
            db.close()

    def show(self):
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.LOCK_OPEN), ft.Text("Apertura de Turno")]),
            content=ft.Container(
                width=400,
                content=ft.Column([
                    ft.Text(f"Bienvenido/a, {self.user['full_name']}", weight="bold", size=18),
                    ft.Text("Verifique los montos en físico antes de iniciar:", color=ft.Colors.GREY_700),
                    ft.Divider(),
                    ft.Row([self.usd_field, self.bs_field]),
                    self.tasa_field,
                    ft.Text("Al confirmar, se registrará el inicio de su jornada.", 
                            size=12, italic=True, color=ft.Colors.BLUE_GREY_400)
                ], tight=True, spacing=15)
            ),
            actions=[
                ft.ElevatedButton("Confirmar y Entrar", 
                                 icon=ft.Icons.CHECK, 
                                 on_click=self.confirm_opening,
                                 bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE)
            ]
        )
        self.page.open(self.dialog)