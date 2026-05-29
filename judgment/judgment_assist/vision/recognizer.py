"""Recognise cards by matching ROIs against a template library.

The game draws cards from fixed sprites, so a reference crop of each card
matches its on-screen copy near-perfectly. We compare a region of interest to
every template (resized to the ROI) with normalised cross-correlation and take
the best score; a confidence floor rejects empty/partly-dealt slots.

Templates live in ``data/templates/<card>.png`` where ``<card>`` is the
shorthand ("As", "Td", "9c"), built by the calibration tool.
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

from ..cards import parse_card, card_str


class CardRecognizer:
    def __init__(self, template_dir, min_confidence=0.6):
        if not _HAVE_DEPS:
            raise RuntimeError("vision needs: pip install numpy opencv-python")
        self.min_confidence = min_confidence
        self.templates = {}  # card-tuple -> grayscale image
        for path in glob.glob(os.path.join(template_dir, "*.png")):
            name = os.path.splitext(os.path.basename(path))[0]
            try:
                card = parse_card(name)
            except ValueError:
                continue  # ignore non-card pngs in the folder
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self.templates[card] = img
        if not self.templates:
            raise RuntimeError(
                f"no card templates found in {template_dir!r} — run the "
                f"calibration tool to build them first")

    def recognize(self, roi_bgr):
        """Return ``(card_tuple, score)`` for the best match, or ``(None, score)``
        if the best score is below ``min_confidence`` (e.g. an empty slot)."""
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        best_card, best_score = None, -1.0
        for card, tmpl in self.templates.items():
            t = cv2.resize(tmpl, (w, h))
            score = float(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best_card, best_score = card, score
        if best_score < self.min_confidence:
            return None, best_score
        return best_card, best_score

    def recognize_many(self, frame_bgr, rois):
        """Recognise a list of ROIs ([l,t,w,h]) within a frame. Returns the list
        of recognised cards (slots below confidence are dropped)."""
        cards = []
        for (l, t, w, h) in rois:
            roi = frame_bgr[t:t + h, l:l + w]
            card, score = self.recognize(roi)
            if card is not None:
                cards.append(card)
        return cards
