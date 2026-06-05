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
        """Left-to-right bounding boxes of digit-sized components.

        This badge font kerns tightly, so two digits often merge into one
        connected component. A blob much wider than a single digit (judged by
        aspect ratio against its own height) is split evenly into the estimated
        number of digits."""
        n, _labels, stats, _c = cv2.connectedComponentsWithStats(thr, connectivity=8)
        h_img = thr.shape[0]
        raw = [(int(s[0]), int(s[1]), int(s[2]), int(s[3])) for s in stats[1:]
               if s[3] >= 0.35 * h_img and s[4] >= 5]   # tall enough, not a speck
        raw.sort(key=lambda b: b[0])
        boxes = []
        for (x, y, w, h) in raw:
            k = max(1, round(w / (0.62 * h)))   # est digits from width/height
            if k == 1:
                boxes.append((x, y, w, h))
            else:
                pw = w // k
                for i in range(k):
                    boxes.append((x + i * pw, y, pw, h))
        return boxes

    def _white_boxes(self, bgr):
        """Digit boxes for a number rendered as WHITE glyphs on a coloured panel
        (the poker pot / chip / bet plates). Otsu fails there — the gold labels
        and border survive it — so isolate white (bright + low-saturation) pixels
        instead, then reuse the merge-splitting box logic. Tuned V>=135 to catch
        anti-aliased glyph edges."""
        white = cv2.inRange(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV),
                            (0, 0, 135), (180, 95, 255))
        white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        # The plate has a bright full-width highlight along its top edge that
        # connects the digit tops into one blob and bleeds into the glyph crops.
        # Zero any near-full-width row to drop it — a digit stroke never spans the
        # whole number ROI. This is what makes the reads reliable (0.8-1.0 conf).
        cov = white.mean(axis=1) / 255.0
        white[cov > 0.7, :] = 0
        return self._digit_boxes(white)

    def read(self, badge_bgr, white=False):
        """Return ``(value:int|None, confidence:float)``. ``None`` when the badge
        can't be read confidently (empty/animating/occluded). ``white=True`` uses
        the white-glyph segmentation for poker UI numbers (vs the Otsu badge path)."""
        if badge_bgr is None or badge_bgr.size == 0 or min(badge_bgr.shape[:2]) < 4:
            return None, 0.0
        gray = cv2.cvtColor(badge_bgr, cv2.COLOR_BGR2GRAY)
        boxes = self._white_boxes(badge_bgr) if white else self._digit_boxes(_binarize(gray))
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

    def read_roi(self, frame_bgr, roi, white=False):
        """Read the badge at ``roi`` = ``[left, top, width, height]`` within a
        full frame. Returns ``(value:int|None, confidence:float)``. ``white=True``
        for white-on-coloured poker UI numbers."""
        l, t, w, h = roi
        return self.read(frame_bgr[t:t + h, l:l + w], white=white)
