import flet as ft
from datetime import datetime, timedelta
from database.connection import SessionLocal
from database.models import Room, RoomStatus, Guest, Stay
from modules.finance.payment_dialog import PaymentDialog

class CheckInDialog:
    def __init__(self, page, room, on_success):
        self.page = page
        self.room = room
        self.on_success = on_success
        self.dialog = None
        self.companions_controls = [] 
        self.current_stay = None 
        # Variable local para el flujo de pago (no se guarda en la tabla stays)
        self.calculated_total = 0.0

        # --- CAMPOS DE FECHA ---
        self.check_in_date = ft.TextField(
            label="Entrada", value=datetime.now().strftime("%Y-%m-%d"),
            read_only=True, expand=1, prefix_icon=ft.Icons.LOGIN
        )
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.check_out_date = ft.TextField(
            label="Salida Estimada", value=tomorrow, expand=1, 
            prefix_icon=ft.Icons.LOGOUT, on_submit=lambda _: self.doc_id.focus()
        )

        # --- CAMPOS DEL HUÉSPED TITULAR ---
        self.doc_id = ft.TextField(
            label="Documento Titular", prefix_icon=ft.Icons.BADGE,
            helper_text="Escriba y pulse Enter para buscar",
            on_submit=self.search_guest_event
        )
        self.first_name = ft.TextField(label="Nombres", expand=1)
        self.last_name = ft.TextField(label="Apellidos", expand=1)
        self.birth_date = ft.TextField(label="F. Nacimiento", hint_text="YYYY-MM-DD", expand=1)
        self.nationality = ft.TextField(label="Nacionalidad", value="Venezolano/a", expand=1)
        self.profession = ft.TextField(label="Profesión", expand=1)
        self.phone = ft.TextField(label="Teléfono", expand=1)
        self.vehicle = ft.TextField(label="Vehículo (Placa/Marca)", prefix_icon=ft.Icons.DIRECTIONS_CAR)
        
        # --- SECCIÓN ACOMPAÑANTES ---
        self.companions_list_container = ft.Column(spacing=10)
        self.btn_add_companion = ft.TextButton(
            "Añadir Acompañante", 
            icon=ft.Icons.ADD_REACTION, 
            on_click=self.add_companion_field
        )

        self.btn_save = ft.ElevatedButton(
            "Registrar Estadía", 
            icon=ft.Icons.SAVE,
            style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_800),
            on_click=self.save_all,
            height=50
        )

    def search_guest_event(self, e):
        self.search_guest(e)
        self.first_name.focus()

    def search_guest(self, e):
        if not self.doc_id.value: return
        db = SessionLocal()
        guest = db.query(Guest).filter(Guest.document_id == self.doc_id.value).first()
        if guest:
            self.first_name.value = guest.first_name
            self.last_name.value = guest.last_name
            self.birth_date.value = guest.birth_date.strftime("%Y-%m-%d") if guest.birth_date else ""
            self.nationality.value = guest.nationality
            self.profession.value = guest.profession
            self.phone.value = guest.phone
            self.vehicle.value = guest.vehicle_info
            self.page.open(ft.SnackBar(ft.Text(f"Huésped {guest.first_name} cargado"), bgcolor="green"))
        db.close()
        self.page.update()

    def add_companion_field(self, e):
        # Usamos max_occupancy del modelo Room
        if len(self.companions_controls) >= (self.room.max_occupancy - 1):
            self.page.open(ft.SnackBar(ft.Text("Capacidad máxima alcanzada"), bgcolor="orange"))
            return

        comp_doc = ft.TextField(label="Doc. Acompañante", expand=2, on_submit=self.search_companion_dynamic)
        comp_name = ft.TextField(label="Nombre", expand=3)
        comp_last = ft.TextField(label="Apellido", expand=3)
        
        row = ft.Row([
            comp_doc, comp_name, comp_last,
            ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color="red", on_click=lambda _: self.remove_companion(row))
        ])
        
        self.companions_controls.append(row)
        self.companions_list_container.controls.append(row)
        self.page.update()
        comp_doc.focus()

    def remove_companion(self, row):
        self.companions_controls.remove(row)
        self.companions_list_container.controls.remove(row)
        self.page.update()

    def search_companion_dynamic(self, e):
        doc_value = e.control.value
        if not doc_value: return
        db = SessionLocal()
        guest = db.query(Guest).filter(Guest.document_id == doc_value).first()
        if guest:
            row_controls = e.control.parent.controls
            row_controls[1].value = guest.first_name
            row_controls[2].value = guest.last_name
        db.close()
        self.page.update()

    def save_all(self, e):
        if not self.doc_id.value or not self.first_name.value:
            self.page.open(ft.SnackBar(ft.Text("Faltan datos del titular"), bgcolor="red"))
            return

        db = SessionLocal()
        try:
            # 1. Procesar Huéspedes
            main_guest = self.get_or_create_guest(db, self.doc_id.value, self.first_name.value, self.last_name.value, True)
            guests_list = [main_guest]

            for row in self.companions_controls:
                doc = row.controls[0].value
                name = row.controls[1].value
                last = row.controls[2].value
                if doc and name:
                    comp = self.get_or_create_guest(db, doc, name, last, False)
                    guests_list.append(comp)

            # 2. Actualizar Habitación
            room_db = db.query(Room).filter(Room.id == self.room.id).first()
            room_db.status = RoomStatus.OCCUPIED
            
            # 3. Calcular Monto (Usando campos reales del modelo Room)
            d1 = datetime.strptime(self.check_in_date.value, "%Y-%m-%d")
            d2 = datetime.strptime(self.check_out_date.value, "%Y-%m-%d")
            nights = max(1, (d2 - d1).days)
            
            # Preferimos current_price_usd si existe, sino base_price_usd
            price_night = room_db.current_price_usd if room_db.current_price_usd else room_db.base_price_usd
            self.calculated_total = nights * price_night
            
            # 4. Crear la Estadía (Solo con campos definidos en class Stay)
            self.current_stay = Stay(
                room_id=room_db.id,
                check_in=d1,
                check_out=d2,
                is_active=True,
                deposit_balance_usd=0.0
            )
            # Vinculamos los huéspedes a través de la relación secondary 'stay_guests'
            self.current_stay.guests = guests_list
            
            db.add(self.current_stay)
            db.commit()
            db.refresh(self.current_stay)
            
            self.page.close(self.dialog)
            self.ask_for_payment()
            
        except Exception as ex:
            db.rollback()
            self.page.open(ft.SnackBar(ft.Text(f"Error en Check-In: {ex}"), bgcolor="red"))
        finally:
            db.close()

    def ask_for_payment(self):
        def go_to_payment(e):
            self.page.close(confirm_dialog)
            # Se envía el total calculado al diálogo de pagos
            payment_dialog = PaymentDialog(
                self.page, 
                self.current_stay, 
                self.calculated_total, 
                on_success=self.on_success
            )
            payment_dialog.show()

        def skip_payment(e):
            self.page.close(confirm_dialog)
            if self.on_success: self.on_success()

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Estadía Registrada"),
            content=ft.Text(f"Total a pagar por {self.room.number}: $ {self.calculated_total:.2f}\n¿Desea registrar el pago ahora?"),
            actions=[
                ft.TextButton("Omitir", on_click=skip_payment),
                ft.ElevatedButton("Cobrar", bgcolor=ft.Colors.GREEN_700, color="white", on_click=go_to_payment),
            ]
        )
        self.page.open(confirm_dialog)

    def get_or_create_guest(self, db, doc, fname, lname, is_main):
        guest = db.query(Guest).filter(Guest.document_id == doc).first()
        if not guest:
            guest = Guest(document_id=doc, first_name=fname, last_name=lname)
            db.add(guest)
        else:
            guest.first_name = fname
            guest.last_name = lname
        
        if is_main:
            try:
                if self.birth_date.value:
                    guest.birth_date = datetime.strptime(self.birth_date.value, "%Y-%m-%d").date()
            except: pass
            guest.nationality = self.nationality.value
            guest.profession = self.profession.value
            guest.phone = self.phone.value
            guest.vehicle_info = self.vehicle.value
        
        db.flush()
        return guest

    def build(self):
        return ft.AlertDialog(
            title=ft.Text(f"Check-In Habitación {self.room.number}"),
            content=ft.Container(
                width=700,
                content=ft.Column([
                    ft.Row([self.check_in_date, self.check_out_date]),
                    ft.Divider(),
                    ft.Text("Datos del Titular", weight="bold", color="blue"),
                    self.doc_id,
                    ft.Row([self.first_name, self.last_name]),
                    ft.Row([self.birth_date, self.nationality]),
                    ft.Row([self.profession, self.phone]),
                    self.vehicle,
                    ft.Divider(),
                    ft.Row([
                        ft.Text("Acompañantes", weight="bold", color="blue"),
                        self.btn_add_companion
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    self.companions_list_container,
                ], scroll=ft.ScrollMode.AUTO, tight=True, spacing=15)
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(self.dialog)),
                self.btn_save
            ]
        )

    def show(self):
        self.dialog = self.build()
        self.page.open(self.dialog)