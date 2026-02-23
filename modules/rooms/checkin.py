import flet as ft
from datetime import datetime
from database.connection import SessionLocal
from database.models import Room, RoomStatus, Guest, Stay

class CheckInDialog:
    def __init__(self, page, room, on_success):
        self.page = page
        self.room = room
        self.on_success = on_success
        self.dialog = None

        # --- CAMPOS DEL TITULAR ---
        self.doc_id = ft.TextField(
            label="Documento", 
            prefix_icon=ft.Icons.BADGE,
            on_blur=self.search_guest, 
            on_submit=lambda _: self.first_name.focus(),
            autofocus=True,
            hint_text="Presione Enter para buscar"
        )
        self.first_name = ft.TextField(
            label="Nombres", 
            prefix_icon=ft.Icons.PERSON,
            on_submit=lambda _: self.last_name.focus(), 
            expand=1
        )
        self.last_name = ft.TextField(
            label="Apellidos", 
            on_submit=lambda _: self.birth_date.focus(), 
            expand=1
        )
        self.birth_date = ft.TextField(
            label="F. Nacimiento", 
            hint_text="AAAA-MM-DD",
            prefix_icon=ft.Icons.CAKE, 
            on_submit=lambda _: self.nationality.focus(), 
            expand=1
        )
        self.nationality = ft.TextField(
            label="Nacionalidad", 
            value="Venezolano/a",
            on_submit=lambda _: self.profession.focus(), 
            expand=1
        )
        self.profession = ft.TextField(
            label="Profesión", 
            prefix_icon=ft.Icons.WORK,
            on_submit=lambda _: self.phone.focus(), 
            expand=1
        )
        self.phone = ft.TextField(
            label="Teléfono", 
            prefix_icon=ft.Icons.PHONE,
            on_submit=lambda _: self.vehicle.focus(), 
            expand=1
        )
        self.vehicle = ft.TextField(
            label="Vehículo (Marca/Placa/Color)", 
            prefix_icon=ft.Icons.DIRECTIONS_CAR,
            on_submit=lambda _: self.save_all(None)
        )
        
        # --- SECCIÓN ACOMPAÑANTE ---
        self.has_companion = ft.Switch(
            label="¿Trae acompañante?", 
            on_change=self.toggle_companion
        )
        self.companion_section = ft.Column(visible=False, spacing=10)
        
        # Campos de acompañante (se inicializan vacíos)
        self.comp_doc = ft.TextField(label="Doc. Acompañante", on_blur=self.search_companion, on_submit=lambda _: self.comp_name.focus())
        self.comp_name = ft.TextField(label="Nombre", on_submit=lambda _: self.comp_last.focus(), expand=1)
        self.comp_last = ft.TextField(label="Apellido", on_submit=lambda _: self.save_all(None), expand=1)

        self.btn_save = ft.ElevatedButton(
            "Finalizar Registro", 
            icon=ft.Icons.CHECK_CIRCLE,
            style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_700),
            on_click=self.save_all,
            height=50
        )

    def search_guest(self, e):
        """Busca al cliente automáticamente por documento"""
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
            self.page.open(ft.SnackBar(ft.Text(f"Cliente {guest.full_name} encontrado"), bgcolor="green"))
        db.close()
        self.page.update()

    def search_companion(self, e):
        """Busca al acompañante automáticamente"""
        if not self.comp_doc.value: return
        db = SessionLocal()
        guest = db.query(Guest).filter(Guest.document_id == self.comp_doc.value).first()
        if guest:
            self.comp_name.value = guest.first_name
            self.comp_last.value = guest.last_name
        db.close()
        self.page.update()

    def toggle_companion(self, e):
        """Muestra u oculta la sección de acompañante"""
        self.companion_section.visible = self.has_companion.value
        if self.has_companion.value:
            self.companion_section.controls = [
                ft.Text("Datos del Acompañante", weight="bold", size=16, color=ft.Colors.BLUE_700),
                self.comp_doc,
                ft.Row([self.comp_name, self.comp_last])
            ]
            self.comp_doc.focus()
        self.page.update()

    def get_or_create_guest(self, db, doc, fname, lname, is_main=True):
        """Busca o crea un huésped y actualiza sus datos adicionales"""
        guest = db.query(Guest).filter(Guest.document_id == doc).first()
        if not guest:
            guest = Guest(document_id=doc, first_name=fname, last_name=lname)
            db.add(guest)
        else:
            guest.first_name = fname
            guest.last_name = lname
        
        # Solo actualizamos datos extra si es el titular
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

    def save_all(self, e):
        """Procesa el registro completo en la BD"""
        if not self.doc_id.value or not self.first_name.value:
            self.page.open(ft.SnackBar(ft.Text("Documento y Nombre son obligatorios"), bgcolor="red"))
            return

        db = SessionLocal()
        try:
            # 1. Registrar/Actualizar Titular
            main_guest = self.get_or_create_guest(db, self.doc_id.value, self.first_name.value, self.last_name.value, True)
            
            guests_in_stay = [main_guest]

            # 2. Registrar/Actualizar Acompañante
            if self.has_companion.value and self.comp_doc.value:
                companion = self.get_or_create_guest(db, self.comp_doc.value, self.comp_name.value, self.comp_last.value, False)
                guests_in_stay.append(companion)

            # 3. Actualizar Habitación y Crear Estadía
            room_db = db.query(Room).filter(Room.id == self.room.id).first()
            room_db.status = RoomStatus.OCCUPIED
            
            new_stay = Stay(
                room_id=room_db.id,
                check_in=datetime.now(),
                is_active=True
            )
            new_stay.guests = guests_in_stay
            
            db.add(new_stay)
            db.commit()
            
            self.page.close(self.dialog)
            self.page.open(ft.SnackBar(ft.Text(f"Check-in exitoso en Hab {self.room.number}"), bgcolor="blue"))
            
            if self.on_success:
                self.on_success()

        except Exception as ex:
            db.rollback()
            print(f"Error en save_all: {ex}")
            self.page.open(ft.SnackBar(ft.Text(f"Error: {str(ex)}"), bgcolor="red"))
        finally:
            db.close()

    def build(self):
        return ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.BED_OUTLINED, color=ft.Colors.BLUE_700),
                ft.Text(f"Check-In Habitación {self.room.number}", weight="bold")
            ]),
            content=ft.Container(
                width=550,
                padding=10,
                content=ft.Column([
                    ft.Text("Información del Huésped Titular", weight="bold", color=ft.Colors.BLUE_700),
                    self.doc_id,
                    ft.Row([self.first_name, self.last_name]),
                    ft.Row([self.birth_date, self.nationality]),
                    ft.Row([self.profession, self.phone]),
                    self.vehicle,
                    ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                    self.has_companion,
                    self.companion_section
                ], scroll=ft.ScrollMode.AUTO, tight=True, spacing=15)
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.page.close(self.dialog)),
                self.btn_save
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )

    def show(self):
        self.dialog = self.build()
        self.page.open(self.dialog)