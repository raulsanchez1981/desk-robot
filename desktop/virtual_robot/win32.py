"""Lo poco de Win32 que hace falta, con ctypes: monitores, área de trabajo y esquinas redondeadas de Windows 11."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def make_dpi_aware() -> None:
    """Coordenadas en píxeles reales en monitores con escalado; sin esto Windows estira la ventana borrosa."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def monitors() -> list[tuple[int, int, int, int]]:
    """Rectángulos (left, top, right, bottom) de todos los monitores."""
    if not IS_WINDOWS:
        return [(0, 0, 1920, 1080)]
    found: list[tuple[int, int, int, int]] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(_RECT), wintypes.LPARAM)

    def cb(_mon, _hdc, rect, _data):
        r = rect.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return found or [(0, 0, 1920, 1080)]


def work_area() -> tuple[int, int, int, int]:
    """Área de trabajo del monitor principal (sin la barra de tareas)."""
    if not IS_WINDOWS:
        return (0, 0, 1920, 1040)
    r = _RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
    return (r.left, r.top, r.right, r.bottom)


def find_window(title: str) -> int:
    return ctypes.windll.user32.FindWindowW(None, title) if IS_WINDOWS else 0


def round_corners(hwnd: int) -> bool:
    """Esquinas redondeadas nativas de Windows 11 (DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND). En Windows 10
    no hace nada."""
    if not IS_WINDOWS or not hwnd:
        return False
    pref = ctypes.c_int(2)
    try:
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(pref),
                                                         ctypes.sizeof(pref)) == 0
    except (AttributeError, OSError):
        return False


def client_size(hwnd: int) -> tuple[int, int]:
    if not IS_WINDOWS or not hwnd:
        return (0, 0)
    r = _RECT()
    ctypes.windll.user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return (r.right - r.left, r.bottom - r.top)


def set_window_rect(hwnd: int, x: int | None, y: int | None, w: int, h: int) -> None:
    """Mueve/redimensiona la ventana en píxeles exactos (pywebview descuenta un borde que una ventana sin marco no
    tiene). x/y None = no moverla."""
    if not IS_WINDOWS or not hwnd:
        return
    SWP_NOZORDER, SWP_NOACTIVATE, SWP_NOMOVE = 0x0004, 0x0010, 0x0002
    flags = SWP_NOZORDER | SWP_NOACTIVATE | (SWP_NOMOVE if x is None else 0)
    ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), None, x or 0, y or 0, w, h, flags)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = _RECT()
    if IS_WINDOWS and hwnd:
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)
