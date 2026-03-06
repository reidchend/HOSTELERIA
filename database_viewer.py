import flet as ft
from database.connection import SesionLocal
import database.models as models
from sqlalchemy import inspect

def main(page: ft.Page):
    page.title = "Inspector de Datos - Estructura Completa"
    page.window_width = 1400
    page.window_height = 900
    page.theme_mode = ft.ThemeMode.LIGHT
    
    # Lista de todos tus modelos para generar las pestañas
    modelos_a_mostrar = [
        ("Huéspedes", models.Huesped),
        ("Habitaciones", models.Habitacion),
        ("Estadías", models.Estadia),
        ("Pagos", models.Pago),
        ("Cargos Extras", models.CargoExtra),
        ("Caja", models.Caja),
        ("Usuarios", models.Usuario),
        ("Turnos", models.Turno),
        ("Configuración", models.Configuracion),
    ]

    def obtener_datos_tabla(modelo):
        db = SesionLocal()
        try:
            # Usamos inspección de SQLAlchemy para obtener TODOS los nombres de columnas
            inst = inspect(modelo)
            columnas = [c_attr.key for c_attr in inst.mapper.column_attrs]
            
            registros = db.query(modelo).all()
            
            # Crear encabezados
            headers = [ft.DataColumn(ft.Text(col.upper(), weight="bold")) for col in columnas]
            
            # Crear filas
            filas = []
            for reg in registros:
                celdas = []
                for col in columnas:
                    valor = getattr(reg, col)
                    # Formateo de valores especiales
                    if valor is None:
                        texto = ""
                    elif hasattr(valor, 'value'): # Para los Enums
                        texto = str(valor.value)
                    elif isinstance(valor, float):
                        texto = f"{valor:,.2f}"
                    else:
                        texto = str(valor)
                    
                    celdas.append(ft.DataCell(ft.Text(texto, size=12)))
                filas.append(ft.DataRow(cells=celdas))
                
            return headers, filas
        except Exception as e:
            print(f"Error cargando {modelo}: {e}")
            return [], []
        finally:
            db.close()

    def construir_pestanas():
        tabs = []
        for nombre, modelo in modelos_a_mostrar:
            headers, filas = obtener_datos_tabla(modelo)
            tabs.append(
                ft.Tab(
                    text=nombre,
                    content=ft.Column([
                        ft.Container(
                            content=ft.DataTable(
                                columns=headers,
                                rows=filas,
                                column_spacing=15,
                                heading_row_color=ft.Colors.BLUE_GREY_50,
                            ),
                            margin=10,
                            border_radius=10,
                        )
                    ], scroll=ft.ScrollMode.ALWAYS, expand=True)
                )
            )
        return tabs

    tabs_control = ft.Tabs(
        selected_index=0,
        tabs=construir_pestanas(),
        expand=1,
        animation_duration=300
    )

    def recargar(e):
        tabs_control.tabs = construir_pestanas()
        page.update()
        page.open(ft.SnackBar(ft.Text("Base de datos sincronizada")))

    page.add(
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.STORAGE, color="blue", size=30),
                ft.Text("EXPLORADOR TOTAL DE TABLAS (SQLITE)", size=24, weight="bold"),
                ft.ElevatedButton("Actualizar Datos", icon=ft.Icons.REFRESH, on_click=recargar),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=20,
            bgcolor=ft.Colors.WHITE,
        ),
        tabs_control
    )

if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=8550)