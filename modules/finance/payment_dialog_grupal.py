# modules/finance/payment_dialog_grupal.py

import flet as ft
from database.connection import SesionLocal
from database.models import (
    MetodoPago,
    Estadia,
    GrupoHabitacion,
    LedgerMovimiento,
    TipoMovimiento,
    FolioLinea,
)
from datetime import datetime


class DialogoPagoGrupal:
    def __init__(self, pagina: ft.Page, grupo: GrupoHabitacion, estadias: list, total_a_pagar: float, al_completar=None, al_pagar_callback=None):
        self.pagina = pagina
        self.grupo = grupo
        self.estadias = estadias
        self.total_a_pagar = total_a_pagar
        self.al_completar = al_completar
        self.al_pagar_callback = al_pagar_callback
        self.dialogo = None
        self.pagos_procesados = []
        self.metodo_seleccionado = None
        
        self._construir_dialogo()

    def _construir_dialogo(self):
        hab_numeros = [str(e.habitacion.numero) for e in self.estadias if e.habitacion]
        
        contenido = ft.Column([
            ft.Container(
                content=ft.Column([
                    ft.Text(f"Grupo: {self.grupo.nombre}", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Habitaciones: {', '.join(hab_numeros)}", size=14),
                    ft.Divider(),
                    ft.Text(f"Total a pagar: ${self.total_a_pagar:.2f}", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                ], spacing=5),
                padding=20,
                bgcolor="#E8E8E8",
                border_radius=10,
            ),
            
            ft.Text("Método de pago", size=14, weight=ft.FontWeight.BOLD),
            self._crear_metodos_pago(),
            self._crear_campos_pago(),

        ], spacing=15, scroll=ft.ScrollMode.AUTO)
        
        self.dialogo = ft.AlertDialog(
            title=ft.Text(f"Pago Grupal - {self.grupo.nombre}"),
            content=ft.Container(content=contenido, width=500, height=450),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.pagina.close(self.dialogo)),
                ft.ElevatedButton("Procesar Pago", on_click=self._procesar_pago),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _crear_metodos_pago(self):
        metodos = [
            ("efectivo_bs", "Efectivo Bs", ft.Icons.MONEY),
            ("efectivo_usd", "Efectivo $", ft.Icons.ATTACH_MONEY),
            ("pago_movil", "Pago Móvil", ft.Icons.PHONE_ANDROID),
            ("transferencia", "Transferencia", ft.Icons.SWAP_HORIZ),
            ("zelle", "Zelle", ft.Icons.EMAIL),
            ("debito", "Tarjeta Débito", ft.Icons.CREDIT_CARD),
        ]
        
        botones = []
        for key, label, icon in metodos:
            botones.append(
                ft.ElevatedButton(
                    text=label,
                    icon=icon,
                    on_click=lambda e, k=key: self._seleccionar_metodo(k),
                    style=ft.ButtonStyle(
                        bgcolor="#E8E8E8",
                    ),
                )
            )
        
        return ft.Column(botones, spacing=5)

    def _crear_campos_pago(self):
        self.campo_monto = ft.TextField(
            label="Monto",
            prefix_icon=ft.Icons.ATTACH_MONEY,
            value=f"{self.total_a_pagar:.2f}",
        )
        self.campo_referencia = ft.TextField(
            label="Referencia (opcional)",
            prefix_icon=ft.Icons.TAG,
            visible=False,
        )
        self.campo_telefono = ft.TextField(
            label="Teléfono (opcional)",
            prefix_icon=ft.Icons.PHONE,
            visible=False,
        )
        
        return ft.Column([self.campo_monto, self.campo_referencia, self.campo_telefono])

    def _seleccionar_metodo(self, metodo):
        self.metodo_seleccionado = metodo
        self.campo_referencia.visible = metodo in ["pago_movil", "transferencia", "zelle"]
        self.campo_telefono.visible = metodo == "pago_movil"
        self.dialogo.update()

    def _procesar_pago(self, _):
        sesion = SesionLocal()
        try:
            monto = float(self.campo_monto.value or 0)
            metodo = self.metodo_seleccionado or 'efectivo_usd'
            
            if monto <= 0:
                self.pagina.open(ft.SnackBar(content=ft.Text("El monto debe ser mayor a 0")))
                return
            
            for est in self.estadias:
                debe = sum(float(m.debe_usd or 0) for m in est.ledger_movimientos)
                haber = sum(float(m.haber_usd or 0) for m in est.ledger_movimientos)
                saldo = debe - haber
                
                if saldo <= 0:
                    continue
                
                monto_a_aplicar = min(monto, saldo) if monto > 0 else 0
                
                if monto_a_aplicar > 0:
                    mov = LedgerMovimiento(
                        estadia_id=est.id,
                        tipo=TipoMovimiento.PAGO,
                        concepto=f"Pago grupal - {self.grupo.nombre}",
                        debe_usd=0,
                        haber_usd=monto_a_aplicar,
                        tasa_cambio=1,
                        referencia=self.campo_referencia.value or "",
                    )
                    sesion.add(mov)
                    
                    for linea in est.folio_lineas:
                        if not linea.cancelada:
                            linea.cancelada = True
                    
                    self.pagos_procesados.append({
                        "metodo": metodo,
                        "monto_usd": monto_a_aplicar,
                        "referencia": self.campo_referencia.value or "",
                    })
            
            sesion.commit()
            
            if self.al_pagar_callback:
                self.al_pagar_callback(self.pagos_procesados)
            
            self.pagina.close(self.dialogo)
            self.pagina.open(ft.SnackBar(content=ft.Text(f"Pago grupal de ${monto:.2f} procesado para {self.grupo.nombre}")))
            
            if self.al_completar:
                self.al_completar()
                
        except Exception as e:
            sesion.rollback()
            print(f"[Error] Pago grupal: {e}")
            self.pagina.open(ft.SnackBar(content=ft.Text(f"Error al procesar pago: {e}")))
        finally:
            sesion.close()

    def mostrar(self):
        self.pagina.open(self.dialogo)