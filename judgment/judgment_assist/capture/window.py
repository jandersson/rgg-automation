"""Locate the game window by title so capture targets it specifically.

For a borderless/windowed Steam game this lets the ROIs stay valid even if the
window is moved: we re-resolve the window's client rectangle each frame and the
card regions are stored relative to it.

Windows-only (ctypes / Win32). Import is guarded so the package still imports on
other platforms / in CI.
"""
from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    def set_dpi_aware():
        """Match mss's physical pixels by opting into per-process DPI awareness.
        Safe to call repeatedly; must run before window rects are read."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        except Exception:
            try:
                _user32.SetProcessDPIAware()
            except Exception:
                pass

    set_dpi_aware()

    def list_windows():
        """Return [(hwnd, title)] for every visible titled window."""
        out = []
        proc_ty = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            if _user32.IsWindowVisible(hwnd):
                n = _user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    _user32.GetWindowTextW(hwnd, buf, n + 1)
                    out.append((hwnd, buf.value))
            return True

        _user32.EnumWindows(proc_ty(_cb), 0)
        return out

    def find_window(title_substring):
        """First visible window whose title contains ``title_substring`` (case
        insensitive). Returns ``(hwnd, title)`` or ``(None, None)``."""
        needle = title_substring.lower()
        for hwnd, title in list_windows():
            if needle in title.lower():
                return hwnd, title
        return None, None

    def foreground_title():
        """Title of the window the user is currently focused on (or '')."""
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def is_foreground(title_substring):
        """True when the focused window's title contains ``title_substring``.
        Used to capture only while the user is actually playing the game — so we
        never grab the paused/dimmed state it shows when it loses focus."""
        return title_substring.lower() in foreground_title().lower()

    def client_region(hwnd):
        """Screen-space rect of the window's client (rendered) area as
        ``{left, top, width, height}``."""
        rect = wintypes.RECT()
        _user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = wintypes.POINT(0, 0)
        _user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return {"left": pt.x, "top": pt.y,
                "width": rect.right - rect.left, "height": rect.bottom - rect.top}

    def find_window_region(title_substring):
        """Convenience: locate a window and return its client region dict, or
        ``None`` if not found."""
        hwnd, _title = find_window(title_substring)
        return client_region(hwnd) if hwnd else None

else:  # pragma: no cover - non-Windows stubs
    def set_dpi_aware():
        pass

    def list_windows():
        return []

    def find_window(title_substring):
        return None, None

    def client_region(hwnd):
        raise RuntimeError("window capture is Windows-only")

    def find_window_region(title_substring):
        return None

    def foreground_title():
        return ""

    def is_foreground(title_substring):
        return False
