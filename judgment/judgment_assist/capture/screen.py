"""Grab a region of the screen as a BGR numpy image via mss.

Source-agnostic: whatever is visible on this PC's monitor (a Steam window, a
PS Remote Play window, a capture-card preview) is captured the same way.
"""
from __future__ import annotations

try:
    import mss
    import numpy as np
    _HAVE_DEPS = True
except Exception:  # pragma: no cover - exercised only without optional deps
    _HAVE_DEPS = False


def _require():
    if not _HAVE_DEPS:
        raise RuntimeError(
            "screen capture needs extra deps: pip install mss numpy opencv-python"
        )


def _as_monitor(region):
    """Normalise a region into the dict mss wants."""
    if region is None:
        return None
    if isinstance(region, dict):
        return region
    left, top, width, height = region  # [l, t, w, h]
    return {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}


class ScreenGrabber:
    def __init__(self, monitor=1):
        _require()
        self._sct = mss.mss()
        self.monitor = monitor

    def list_monitors(self):
        return list(enumerate(self._sct.monitors))

    def grab(self, region=None):
        """Return a BGR uint8 array. ``region`` is [left, top, w, h] / dict /
        None (whole selected monitor)."""
        mon = _as_monitor(region) or self._sct.monitors[self.monitor]
        raw = self._sct.grab(mon)
        img = np.array(raw)          # BGRA
        return img[:, :, :3].copy()  # drop alpha -> BGR

    def close(self):
        self._sct.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
