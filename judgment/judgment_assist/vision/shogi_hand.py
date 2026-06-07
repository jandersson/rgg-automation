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


def load_native_templates(templates_dir, owner):
    """``{code: grayscale image}`` at native size for one owner. ``owner`` is
    ``'b'`` (your/uppercase pieces) or ``'w'`` (opponent/lowercase)."""
    path = os.path.join(templates_dir, MANIFEST)
    out = {}
    for stem, code in json.load(open(path, encoding="utf-8")).items():
        want_upper = owner == "b"
        if code.isupper() != want_upper:
            continue
        img = cv2.imread(os.path.join(templates_dir, stem))
        if img is not None:
            out[code] = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return out


def read_hand(frame, tray_roi, natives, threshold=0.6, scales=(0.85, 1.0, 1.15)):
    """Count captured pieces in one tray. ``natives`` is :func:`load_native_templates`
    for that tray's owner. Returns ``{code: count}``."""
    if not _HAVE_DEPS:
        raise RuntimeError("komadai reading needs: pip install opencv-python numpy")
    l, t, w, h = tray_roi
    tray = cv2.cvtColor(frame[t:t + h, l:l + w], cv2.COLOR_BGR2GRAY)
    dets = []
    for code, tmpl in natives.items():
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
    for d in dets:                                # non-max suppression by centre distance
        if all(abs(d[1] - k[1]) > 0.5 * d[3] or abs(d[2] - k[2]) > 0.5 * d[4] for k in kept):
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
