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
        # label (tuple|int) -> list of grayscale exemplar images. Multiple
        # exemplars per rank cover suit/colour variation (a red 9-diamonds vs a
        # black 9-spades correlate differently in grayscale); matching takes the
        # best over all exemplars. Files are '<label>.png' or '<label>_<tag>.png'
        # (e.g. Q.png, Q_clubs.png) — the part before '_' is the label.
        self.templates = {}
        for path in sorted(glob.glob(os.path.join(template_dir, "*.png"))):
            stem = os.path.splitext(os.path.basename(path))[0]
            try:
                label = label_of(stem.split("_")[0])  # also filters the other mode's files
            except ValueError:
                continue
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self.templates.setdefault(label, []).append(img)
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
        for label, exemplars in self.templates.items():
            for tmpl in exemplars:
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

    def scan_ranks(self, region_bgr, min_score=0.6, merge_dist=None, floors=None,
                   scales=(1.0, 0.9, 0.8)):
        """Slide every template over ``region_bgr`` (a card cluster's corner strip)
        and return matches top-to-bottom: ``[(label, score, (x, y, w, h)), ...]``.

        Unlike ``recognize`` (one ROI -> one label), this finds glyphs *wherever*
        they sit in the region, so a cascade of overlapping cards is read without
        needing per-card ROI segmentation (the fragile part). The mirrored
        bottom-corner indices are 180°-rotated and don't match the upright
        templates.

        Validated on real frames: number/ace/ten ranks (the count-relevant bulk)
        score >=0.66 and read correctly even in overlapping cascades; the weakest
        spurious match (the low-contrast Q glyph against card decoration) tops out
        ~0.58, so ``min_score=0.6`` separates them cleanly. Court letters (J/Q/K)
        sit at the extreme card corner and scan-match weakly — improving those is
        tracked separately; raising ``min_score`` would otherwise misread them.

        Matches within ``merge_dist`` px (vertically) collapse to the
        highest-scoring one — that dedupes both the correlation plateau around a
        glyph and several templates peaking on the same glyph. Cards cascade with
        an offset far larger than a glyph, so distinct cards survive.

        ``floors`` is an optional ``{label: min_score}`` override for ranks whose
        template false-matches more readily than the rest. Measured: the Q glyph
        weakly correlates with card-interior decoration up to ~0.62 while a real Q
        scores ~0.95, so a higher Q floor drops the spurious ones cleanly."""
        gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape[:2]
        floors = floors or {}
        # Cards render at slightly different sizes by cascade position (a lower
        # card can be ~0.8x the template). Match each template at a few scales and
        # keep the best -- measured: a 3 that scores 0.36 at 1.0x scores 0.92 at
        # 0.8x. NMS below collapses the same glyph found at neighbouring scales.
        dets = []  # (score, label, x, y, w, h)
        for label, exemplars in self.templates.items():
            lbl_min = floors.get(label, min_score)
            for tmpl in exemplars:
                for s in scales:
                    t = tmpl if s == 1.0 else cv2.resize(tmpl, None, fx=s, fy=s)
                    th, tw = t.shape[:2]
                    if th > H or tw > W or th < 8 or tw < 8:
                        continue
                    res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
                    ys, xs = np.where(res >= lbl_min)
                    for y, x in zip(ys.tolist(), xs.tolist()):
                        dets.append((float(res[y, x]), label, x, y, tw, th))
        dets.sort(reverse=True)  # best score first
        kept = []
        for score, label, x, y, w, h in dets:
            cy = y + h / 2.0
            tol = merge_dist if merge_dist is not None else max(12, 0.5 * h)
            if any(abs(cy - (ky + kh / 2.0)) < tol for _, _, _, ky, _, kh in kept):
                continue
            kept.append((score, label, x, y, w, h))
        kept.sort(key=lambda d: d[3])  # top-to-bottom
        return [(label, score, (x, y, w, h)) for score, label, x, y, w, h in kept]

    def label_str(self, label):
        """Human-readable form of a label, for either mode."""
        return card_str(label) if self.mode == "card" else INT_TO_RANK[label]
