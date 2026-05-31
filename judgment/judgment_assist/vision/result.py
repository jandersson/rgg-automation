"""Detect Judgment's end-of-hand result banner.

At the end of a hand the game flashes a large banner over the table centre —
``BLACKJACK`` (gold), ``YOU WIN`` / ``YOU LOSE`` (white), ``PUSH`` (green). That
banner is a *definitive* hand-end signal (far more reliable than guessing from a
gap in card reads) and it names the outcome — useful for a session tally.

Templates live in ``data/results/<CUE>.png`` (cropped at 1920x1080). We scan a
central band — below the permanent felt "BLACK JACK" title, where the result
banners render — and template-match each; the best match above ``min_score``
wins. BUST is intentionally NOT a template (its red on-card text is mostly
background and false-matched the felt/cards): a bust is already known from the
HUD player total (>21).

Validated on real frames: each cue self-matches 1.0 on its own frame; no-banner
frames score <=0.25, so 0.6 separates cleanly.
"""
from __future__ import annotations

import glob
import os

try:
    import cv2
    import numpy as np  # noqa: F401  (cv2 pulls it in; kept explicit for parity)
    _HAVE_DEPS = True
except Exception:  # pragma: no cover
    _HAVE_DEPS = False

# Central banner band as fractions of frame size (tuned at 1920x1080: rows
# 460-600, cols 450-1450). Fractions so other resolutions degrade gracefully.
_BAND = (0.426, 0.556, 0.234, 0.755)  # y0, y1, x0, x1


class ResultReader:
    def __init__(self, results_dir, min_score=0.6):
        if not _HAVE_DEPS:
            raise RuntimeError("vision needs: pip install numpy opencv-python")
        self.min_score = min_score
        self.templates = {}  # cue name (UPPER) -> grayscale template
        for path in sorted(glob.glob(os.path.join(results_dir, "*.png"))):
            cue = os.path.splitext(os.path.basename(path))[0].upper()
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self.templates[cue] = img
        if not self.templates:
            raise RuntimeError(f"no result-cue templates in {results_dir!r}")

    def read(self, frame_bgr):
        """Return the outcome cue showing this frame (``'WIN'``, ``'LOSE'``,
        ``'PUSH'``, ``'BLACKJACK'``) or ``None`` if no banner is up."""
        h, w = frame_bgr.shape[:2]
        y0, y1, x0, x1 = (int(_BAND[0] * h), int(_BAND[1] * h),
                          int(_BAND[2] * w), int(_BAND[3] * w))
        band = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        best, best_score = None, self.min_score
        for cue, tmpl in self.templates.items():
            if tmpl.shape[0] > band.shape[0] or tmpl.shape[1] > band.shape[1]:
                continue
            score = float(cv2.matchTemplate(band, tmpl, cv2.TM_CCOEFF_NORMED).max())
            if score >= best_score:
                best, best_score = cue, score
        return best
