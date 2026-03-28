# modules/ui/floating_window.py
# Sistema de ventanas flotantes para Flet

import flet as ft
from typing import Callable, Optional


class FloatingWindowManager:
    """Gestor central de ventanas flotantes (Singleton)"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._windows = {}
            cls._instance._stack = None
        return cls._instance
    
    def set_stack(self, stack):
        self._stack = stack
    
    def get_stack(self):
        return self._stack
    
    def register_window(self, window_id: str, window: 'FloatingWindow'):
        self._windows[window_id] = window
    
    def unregister_window(self, window_id: str):
        if window_id in self._windows:
            del self._windows[window_id]
    
    def get_window(self, window_id: str) -> Optional['FloatingWindow']:
        return self._windows.get(window_id)
    
    def close_all(self):
        for window in list(self._windows.values()):
            window.close()
    
    def minimize_all(self):
        for window in self._windows.values():
            window.minimize()


class FloatingWindow:
    """
    Ventana flotante que puede:
    - Arrastrarse con el mouse
    - Minimizarse a un dock
    - Maximizarse/restaurarse
    - Cerrarse
    - Estar siempre visible sobre otros controles
    """
    
    def __init__(
        self,
        page: ft.Page,
        title: str,
        content: ft.Control,
        width: float = 400,
        height: float = 500,
        x: float = None,
        y: float = None,
        icon: str = "WINDOW",
        on_close: Callable = None,
        resizable: bool = True,
    ):
        self.page = page
        self.title = title
        self.content = content
        self.icon = icon
        self.on_close = on_close
        self.resizable = resizable
        self._minimized = False
        self._maximized = False
        self._dragging = False
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        
        self.window_id = f"fw_{id(self)}"
        
        if x is None:
            x = (page.width - width) / 2
        if y is None:
            y = (page.height - height) / 2
        
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._saved_x = x
        self._saved_y = y
        self._saved_width = width
        self._saved_height = height
        
        self.manager = FloatingWindowManager()
        self.manager.register_window(self.window_id, self)
        
        self._build_controls()
    
    def _build_controls(self):
        title_row = ft.Row(
            [
                ft.Icon(self.icon, size=18, color=ft.Colors.WHITE),
                ft.Text(
                    self.title,
                    color=ft.Colors.WHITE,
                    size=14,
                    weight=ft.FontWeight.W_500,
                    expand=True,
                ),
                ft.IconButton(
                    icon=ft.Icons.MINIMIZE,
                    icon_color=ft.Colors.WHITE,
                    icon_size=16,
                    on_click=lambda _: self.minimize(),
                    tooltip="Minimizar",
                ),
                ft.IconButton(
                    icon=ft.Icons.CROP_SQUARE,
                    icon_color=ft.Colors.WHITE,
                    icon_size=16,
                    on_click=lambda _: self.toggle_maximize(),
                    tooltip="Maximizar",
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=ft.Colors.WHITE,
                    icon_size=16,
                    on_click=lambda _: self.close(),
                    tooltip="Cerrar",
                ),
            ],
            spacing=8,
        )
        
        drag_area = ft.WindowDragArea(
            content=ft.Container(
                content=title_row,
                bgcolor=ft.Colors.BLUE_GREY_700,
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border_radius=ft.border_radius.only(top_left=8, top_right=8),
            ),
        )
        
        self._content_container = ft.Container(
            content=self.content,
            expand=True,
            padding=10,
        )
        
        self._window_container = ft.Container(
            content=ft.Column(
                [
                    drag_area,
                    self._content_container,
                ],
                spacing=0,
            ),
            width=self._width,
            height=self._height,
            left=self._x,
            top=self._y,
            border=ft.border.all(1, ft.Colors.BLUE_GREY_300),
            border_radius=8,
            shadow=ft.BoxShadow(
                spread_radius=3,
                blur_radius=10,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
            ),
            bgcolor=ft.Colors.WHITE,
        )
    
    def _bring_to_front(self):
        max_z = 100
        for w in self.manager._windows.values():
            if hasattr(w, '_window_container'):
                current_z = getattr(w._window_container, 'current_z_index', 100)
                max_z = max(max_z, current_z)
        
        self._window_container.current_z_index = max_z + 1
        self.page.update()
    
    def show(self):
        self._window_container.visible = True
        self._minimized = False
        
        if self._window_container not in self.page.overlay:
            self.page.overlay.append(self._window_container)
        
        self._bring_to_front()
        self.page.update()
    
    def close(self):
        if self._window_container in self.page.overlay:
            self.page.overlay.remove(self._window_container)
        self.manager.unregister_window(self.window_id)
        
        if callable(self.on_close):
            self.on_close()
        
        self.page.update()
    
    def minimize(self):
        self._window_container.visible = False
        self._minimized = True
        self.page.update()
    
    def toggle_maximize(self, e=None):
        if not self.resizable:
            return
            
        if self._maximized:
            self._window_container.width = self._saved_width
            self._window_container.height = self._saved_height
            self._window_container.left = self._saved_x
            self._window_container.top = self._saved_y
            self._maximized = False
        else:
            self._saved_x = self._x
            self._saved_y = self._y
            self._saved_width = self._width
            self._saved_height = self._height
            self._window_container.width = self.page.width - 40
            self._window_container.height = self.page.height - 40
            self._window_container.left = 20
            self._window_container.top = 20
            self._maximized = True
        
        self._window_container.update()
        self.page.update()
    
    @property
    def is_minimized(self) -> bool:
        return self._minimized


def show_floating_window(
    page: ft.Page,
    title: str,
    content: ft.Control,
    width: float = 450,
    height: float = 550,
    icon: str = "WINDOW",
    on_close: Callable = None,
) -> FloatingWindow:
    """
    Crea y muestra una ventana flotante.
    
    Returns:
        FloatingWindow: La instancia de la ventana creada
    """
    window = FloatingWindow(
        page=page,
        title=title,
        content=content,
        width=width,
        height=height,
        icon=icon,
        on_close=on_close,
    )
    window.show()
    return window


class FloatingDock:
    """Dock que muestra las ventanas minimizadas"""
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.manager = FloatingWindowManager()
        self._container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text("Ventanas", size=12, weight="bold"),
                        padding=5,
                    ),
                ],
                spacing=0,
            ),
            visible=False,
            right=10,
            bottom=10,
            bgcolor=ft.Colors.BLUE_GREY_100,
            border_radius=8,
            border=ft.border.all(1, ft.Colors.BLUE_GREY_300),
        )
    
    def get_container(self):
        return self._container
    
    def refresh(self):
        minimized = [w for w in self.manager._windows.values() if w.is_minimized]
        if not minimized:
            self._container.visible = False
        else:
            self._container.content.controls = [
                ft.Container(
                    content=ft.Text("Ventanas", size=12, weight="bold"),
                    padding=5,
                ),
            ]
            for window in minimized:
                self._container.content.controls.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(window.icon, size=20),
                                ft.Text(window.title[:10] if len(window.title) > 10 else window.title, size=10),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=2,
                        ),
                        padding=8,
                        on_click=lambda _, w=window: w.show(),
                        tooltip=window.title,
                    )
                )
            self._container.visible = True
        self.page.update()
