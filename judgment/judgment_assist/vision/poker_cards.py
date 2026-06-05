"""Best-effort hole-card recognition for the semi-auto poker overlay.

This is the one place the project reads card *content*, and it is deliberately
**advisory, not authoritative**: screen-scraped poker rank reading is the
documented ~75-80% wall (see POKER.md), so this seeds the overlay with a guess
you confirm or correct — it never decides on its own.

What's reliable vs. not (measured on the labeled corners):
* **suit colour** red/black ≈ 95% — ink-pixel redness, the strong signal.
* **rank** ≈ 50-60% — nearest-exemplar template match; a hint, expect to fix it.

Method: each card's top-left corner (rank glyph over suit pip) is matched
against the labeled corner crops in ``data/poker_cards`` (the same crops used for
labeling — a perfect 1:1 exemplar set once downscaled). Rank = the rank of the
best-correlating exemplar; suit = nearest exemplar *within the detected colour*.
Everything is normalised to a canonical corner size so it survives a resolution
change.
"""
from __future__ import annotations

import glob
import json
import os

try:
    import cv2
    import numpy as np
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False

from ..cards import RANK_TO_INT, SUIT_TO_INT

# Canonical corner geometry (the config's default) and the rank/suit sub-boxes
# within it, as (y0, y1, x0, x1). The suit box is read in colour for the red test.
_CORNER = (70, 105)                       # (w, h)
_RANK_BOX = (4, 60, 2, 54)
_SUIT_BOX = (56, 100, 0, 52)
_SUIT_LETTER = {"clubs": "c", "diamonds": "d", "hearts": "h", "spades": "s"}
_RED = {SUIT_TO_INT["h"], SUIT_TO_INT["d"]}


def _ink_bbox(gray):
    """Tight crop around the dark glyph ink (so a template slides over a query)."""
    th = gray < (int(gray.mean()) - 15)
    ys, xs = np.where(th)
    if len(xs) < 10:
        return gray
    return gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _is_red(suit_bgr):
    """True if this suit pip is red (hearts/diamonds) by ink-pixel redness — the
    average over the DARK pixels only (the white card body dilutes a whole-region
    mean). Reliable where shape matching is not."""
    g = cv2.cvtColor(suit_bgr, cv2.COLOR_BGR2GRAY)
    ink = g < (int(g.mean()) - 10)
    if ink.sum() < 5:
        return False
    b, gr, r = (suit_bgr[..., 0].astype(int), suit_bgr[..., 1].astype(int),
                suit_bgr[..., 2].astype(int))
    return float((r - (gr + b) / 2)[ink].mean()) > 10


def _best(query_gray, templates):
    """Rank/suit label of the highest-correlating exemplar template (shift-
    tolerant ``TM_CCOEFF_NORMED``), plus that score."""
    best, score = None, -2.0
    for label, t in templates:
        tt = t
        if tt.shape[0] > query_gray.shape[0] or tt.shape[1] > query_gray.shape[1]:
            tt = cv2.resize(tt, (min(tt.shape[1], query_gray.shape[1]),
                                 min(tt.shape[0], query_gray.shape[0])))
        s = float(cv2.matchTemplate(query_gray, tt, cv2.TM_CCOEFF_NORMED).max())
        if s > score:
            best, score = label, s
    return best, score


class HoleCardReader:
    """Loads the labeled corner crops as an exemplar library and recognises a
    card from its corner. Advisory only — pair with human correction."""

    def __init__(self, card_dir="data/poker_cards"):
        if not _HAVE:
            raise RuntimeError("card reader needs numpy + opencv")
        labels_path = os.path.join(card_dir, "labels.json")
        if not os.path.exists(labels_path):
            raise RuntimeError(
                f"no labeled crops in {card_dir!r} — the hole-card reader needs "
                f"labels.json + the corner PNGs (build with label --poker)")
        labels = json.load(open(labels_path, encoding="utf-8"))
        self._rank_ex = []     # (rank_int, tight_gray_template)
        self._suit_ex = {True: [], False: []}   # is_red -> (suit_int, tight_gray)
        for key, lab in labels.items():
            if lab.get("_skip") or "rank" not in lab:
                continue
            frame, slot = key.split("#")
            path = os.path.join(card_dir, f"{frame}_{slot}.png")
            crop = cv2.imread(path)
            if crop is None:
                continue
            corner = cv2.resize(crop, _CORNER)
            rg, sg = self._regions(corner)
            self._rank_ex.append((RANK_TO_INT[lab["rank"]], _ink_bbox(rg)))
            suit_int = SUIT_TO_INT[_SUIT_LETTER[lab["suit"]]]
            suit_gray = cv2.cvtColor(sg, cv2.COLOR_BGR2GRAY)
            self._suit_ex[suit_int in _RED].append((suit_int, _ink_bbox(suit_gray)))
        if not self._rank_ex:
            raise RuntimeError(f"no usable exemplars in {card_dir!r}")

    @staticmethod
    def _regions(corner_bgr):
        """(rank_gray, suit_gray) sub-regions of a canonical-size corner."""
        y0, y1, x0, x1 = _RANK_BOX
        rank = cv2.cvtColor(corner_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        y0, y1, x0, x1 = _SUIT_BOX
        return rank, corner_bgr[y0:y1, x0:x1]

    def recognize(self, corner_bgr):
        """Recognise the card in a single card-corner crop.

        Returns ``(card, info)`` where ``card`` is a ``(rank, suit)`` tuple (the
        best guess) and ``info`` carries ``rank_conf`` and ``color`` ('red'/
        'black') so the overlay can flag low-confidence reads."""
        corner = cv2.resize(corner_bgr, _CORNER)
        rank_g, suit_bgr = self._regions(corner)
        rank, rank_conf = _best(rank_g, self._rank_ex)
        red = _is_red(suit_bgr)
        suit_g = cv2.cvtColor(suit_bgr, cv2.COLOR_BGR2GRAY)
        ex = self._suit_ex[red] or self._suit_ex[not red]
        suit, _ = _best(suit_g, ex)
        return (rank, suit), {"rank_conf": rank_conf, "color": "red" if red else "black"}

    def read_hole(self, frame_bgr, cfg):
        """Detect both hole cards from a full frame. Returns a list of
        ``(card, info)`` for each face-up hole slot, or ``None`` for an empty /
        animating slot (so a half-dealt hand reads as 'not ready')."""
        from .poker import card_present
        cw, ch = cfg["corner"]
        out = []
        for x, y in cfg["hole"]:
            corner = frame_bgr[y:y + ch, x:x + cw]
            if corner.shape[:2] != (ch, cw) or not card_present(corner):
                out.append(None)
            else:
                out.append(self.recognize(corner))
        return out
