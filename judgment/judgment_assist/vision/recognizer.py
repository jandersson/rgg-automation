"""Recognise cards (or just ranks) by matching ROIs against a template library.

The game draws cards from fixed sprites, so a reference crop matches its
on-screen copy near-perfectly. We compare a region of interest to every template
(resized to the ROI) with normalised cross-correlation and take the best score;
a confidence floor rejects empty/partly-dealt slots.

Two modes:

* ``mode="card"`` (poker) — full rank+suit. Templates are ``<card>.png`` such as
  ``As.png`` / ``Td.png``; recognition returns ``(rank, suit)`` tuples. Suits
  matter (flushes), so the library needs all 52.

* ``mode="rank"`` (blackjack) — rank only. Templates are ``<rank>.png`` such as
  ``A.png`` / ``K.png`` / ``T.png`` (point the ROI at the rank glyph in the
  card's corner). Recognition returns rank ints. Only 13 templates needed and
  suit is ignored — exactly what blackjack wants.

A single ``data/templates`` folder can hold both: each mode only loads the
filenames that parse for it.
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

from ..cards import parse_card, card_str, RANK_TO_INT, INT_TO_RANK


def _card_label(stem):
    """'As' -> (14, 3). Raises ValueError if not a full card."""
    return parse_card(stem)


def _rank_label(stem):
    """'A' -> 14. Raises ValueError if not a single rank."""
    r = stem.strip().upper()
    if r not in RANK_TO_INT:
        raise ValueError(f"not a rank: {stem!r}")
    return RANK_TO_INT[r]


_LABELERS = {"card": _card_label, "rank": _rank_label}


class CardRecognizer:
    def __init__(self, template_dir, mode="card", min_confidence=0.6):
        if not _HAVE_DEPS:
            raise RuntimeError("vision needs: pip install numpy opencv-python")
        if mode not in _LABELERS:
            raise ValueError(f"mode must be one of {list(_LABELERS)}")
        self.mode = mode
        self.min_confidence = min_confidence
        label_of = _LABELERS[mode]
        self.templates = {}  # label (tuple|int) -> grayscale image
        for path in glob.glob(os.path.join(template_dir, "*.png")):
            stem = os.path.splitext(os.path.basename(path))[0]
            try:
                label = label_of(stem)  # also filters out the other mode's files
            except ValueError:
                continue
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self.templates[label] = img
        if not self.templates:
            raise RuntimeError(
                f"no {mode} templates found in {template_dir!r} — build them "
                f"with the calibration tool (templates --mode {mode}) first")

    def recognize(self, roi_bgr):
        """Return ``(label, score)`` for the best match, or ``(None, score)`` if
        the best score is below ``min_confidence`` (e.g. an empty slot). ``label``
        is a ``(rank, suit)`` tuple in card mode or a rank int in rank mode."""
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        best_label, best_score = None, -1.0
        for label, tmpl in self.templates.items():
            t = cv2.resize(tmpl, (w, h))
            score = float(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best_label, best_score = label, score
        if best_score < self.min_confidence:
            return None, best_score
        return best_label, best_score

    def recognize_many(self, frame_bgr, rois):
        """Recognise a list of ROIs (``[l, t, w, h]``) within a frame. Returns
        the list of recognised labels (slots below confidence are dropped)."""
        labels = []
        for (l, t, w, h) in rois:
            label, _score = self.recognize(frame_bgr[t:t + h, l:l + w])
            if label is not None:
                labels.append(label)
        return labels

    def label_str(self, label):
        """Human-readable form of a label, for either mode."""
        return card_str(label) if self.mode == "card" else INT_TO_RANK[label]
