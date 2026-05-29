"""Read the integer shown in a HUD badge (dealer total / player total).

Judgment renders the dealer up-card value and the player's hand total as clean
numerals in fixed, flat badges. Unlike the tilted card fan, these are
position-stable and high-contrast, so digit recognition is reliable.

Approach: threshold the badge, find the digit-sized connected components, read
each left-to-right by matching it against a digit-template library
(``data/digits/<0-9>.png``, built by the calibration tool), and concatenate.

The auto-invert step makes it work whether the digits are light-on-dark (the
in-game badges) or dark-on-light, so templates and live badges don't have to
agree on polarity.
"""
from __future__ import annotations

import glob
import os

try:
    import cv2
    import numpy as np
    _HAVE_DEPS = True
except Exception:  # pragma: no cover
    _HAVE_DEPS = False


def _binarize(gray):
    """Otsu threshold with digits forced to white (the minority pixels)."""
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    if np.mean(thr) > 127:          # digits should be the minority -> invert
        thr = cv2.bitwise_not(thr)
    return thr


class HudReader:
    def __init__(self, digit_dir, min_confidence=0.55):
        if not _HAVE_DEPS:
            raise RuntimeError("HUD reader needs: pip install numpy opencv-python")
        self.min_confidence = min_confidence
        self.templates = {}  # int 0-9 -> grayscale tight glyph
        for path in glob.glob(os.path.join(digit_dir, "*.png")):
            stem = os.path.splitext(os.path.basename(path))[0]
            if len(stem) == 1 and stem.isdigit():
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    self.templates[int(stem)] = img
        if not self.templates:
            raise RuntimeError(
                f"no digit templates in {digit_dir!r} — build them with the "
                f"calibration tool (digits mode) first")

    def _digit_boxes(self, thr):
        """Left-to-right bounding boxes of digit-sized components."""
        n, _labels, stats, _c = cv2.connectedComponentsWithStats(thr, connectivity=8)
        h_img = thr.shape[0]
        boxes = [(s[0], s[1], s[2], s[3]) for s in stats[1:]
                 if s[3] >= 0.4 * h_img and s[4] >= 6]   # tall enough, not a speck
        boxes.sort(key=lambda b: b[0])
        return boxes

    def read(self, badge_bgr):
        """Return ``(value:int|None, confidence:float)``. ``None`` when the badge
        can't be read confidently (empty/animating/occluded)."""
        gray = cv2.cvtColor(badge_bgr, cv2.COLOR_BGR2GRAY)
        thr = _binarize(gray)
        boxes = self._digit_boxes(thr)
        if not boxes:
            return None, 0.0
        digits, scores = [], []
        for (x, y, w, h) in boxes:
            glyph = gray[y:y + h, x:x + w]
            best_d, best_s = None, -1.0
            for d, tmpl in self.templates.items():
                t = cv2.resize(tmpl, (w, h))
                s = float(cv2.matchTemplate(glyph, t, cv2.TM_CCOEFF_NORMED).max())
                if s > best_s:
                    best_d, best_s = d, s
            digits.append(str(best_d))
            scores.append(best_s)
        conf = min(scores)
        if conf < self.min_confidence:
            return None, conf
        return int("".join(digits)), conf
