"""Komadai (captured-piece pool) reading -> SFEN hands.

Each player has a tray ("komadai") holding captured pieces, which they may *drop*
back onto the board — central to shogi, so the advisor needs them. We slide the
piece templates over each tray region and non-max-suppress the hits into a count
per piece type. Your tray holds your pieces (upright = uppercase templates); the
opponent's holds theirs (inverted = lowercase templates).

v1 limitations: counts = number of *distinct icons* found, so if the game collapses
duplicates into one icon + a "×N" number, this undercounts (reading that digit is
a TODO). The hand cursor sitting over a tray hides its pieces for that frame; the
next clean frame recovers them.
"""
from __future__ import annotations

import json
import os

try:
    import cv2
    import numpy as np
    _HAVE_DEPS = True
except Exception:  # pragma: no cover
    _HAVE_DEPS = False

from .shogi_pieces import MANIFEST


# Only these can sit in a hand: pieces in hand are always unpromoted, and a king
# is never captured. So we never match promoted pieces or kings against a pool.
_DROPPABLE = set("PLNSGBR")


def load_native_templates(templates_dir, owner):
    """``{code: [grayscale image, ...]}`` at native size for one owner's droppable
    pieces. ``owner`` is ``'b'`` (your/uppercase) or ``'w'`` (opponent/lowercase).
    Promoted pieces and kings are excluded — they can't be in hand."""
    path = os.path.join(templates_dir, MANIFEST)
    out = {}
    for stem, code in json.load(open(path, encoding="utf-8")).items():
        if code.startswith("+") or code.upper() not in _DROPPABLE:
            continue
        if code.isupper() != (owner == "b"):
            continue
        img = cv2.imread(os.path.join(templates_dir, stem))
        if img is not None:
            out.setdefault(code, []).append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    return out


def read_hand(frame, tray_roi, natives, threshold=0.65, scales=(0.85, 1.0, 1.15)):
    """Count captured pieces in one tray. ``natives`` is :func:`load_native_templates`
    for that tray's owner (``{code: [templates]}``). Returns ``{code: count}``.

    Each accepted match must also contain a real kanji glyph (dark strokes) — wood
    grain, the tray UI text and the hand cursor have none, so this kills the false
    matches an empty/near-empty tray otherwise produces."""
    if not _HAVE_DEPS:
        raise RuntimeError("komadai reading needs: pip install opencv-python numpy")
    from .shogi_board import glyph_fraction
    l, t, w, h = tray_roi
    tray = cv2.cvtColor(frame[t:t + h, l:l + w], cv2.COLOR_BGR2GRAY)
    dets = []
    for code, tmpls in natives.items():
        for tmpl in tmpls:
            for s in scales:
                ts = cv2.resize(tmpl, (max(8, int(tmpl.shape[1] * s)),
                                       max(8, int(tmpl.shape[0] * s))))
                if ts.shape[0] >= tray.shape[0] or ts.shape[1] >= tray.shape[1]:
                    continue
                res = cv2.matchTemplate(tray, ts, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(res >= threshold)
                for x, y in zip(xs, ys):
                    dets.append((float(res[y, x]), int(x), int(y), ts.shape[1], ts.shape[0], code))
    dets.sort(reverse=True)                       # strongest first
    kept = []
    for d in dets:
        score, x, y, tw, th, code = d
        if any(abs(x - k[1]) <= 0.5 * tw and abs(y - k[2]) <= 0.5 * th for k in kept):
            continue                              # non-max suppression by centre distance
        if glyph_fraction(tray[y:y + th, x:x + tw]) < 0.02:
            continue                              # no kanji here -> wood/UI/finger false match
        kept.append(d)
    counts = {}
    for d in kept:
        counts[d[5]] = counts.get(d[5], 0) + 1
    return counts


def read_hands(frame, you_roi, opp_roi, templates_dir, threshold=0.6):
    """Read both trays -> combined ``{code: count}`` (uppercase = your hand,
    lowercase = opponent's) for :func:`vision.shogi_board.grid_to_sfen`."""
    hands = {}
    hands.update(read_hand(frame, you_roi, load_native_templates(templates_dir, "b"), threshold))
    hands.update(read_hand(frame, opp_roi, load_native_templates(templates_dir, "w"), threshold))
    return hands
