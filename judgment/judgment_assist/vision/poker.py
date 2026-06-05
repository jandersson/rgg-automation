"""Poker table reading from the fixed 'poker' ROIs in the region config.

The card *content* (rank+suit) needs the template library that's being labeled
(`build_poker_task`). This module covers what's readable WITHOUT any templates —
pure geometry + a card-face test:

* ``card_present`` — is a face-up card sitting in this corner ROI? (A real card
  corner is mostly bright white card-face with a small dark glyph; an empty slot
  is green felt, a centred result banner is dark, an opponent back is red.)
* ``board_count`` / ``street`` — how many community cards are dealt → which
  street we're on. The advisor needs the street, and it's label-free.
"""
from __future__ import annotations

try:
    import cv2
    import numpy as np
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False

from .locate import _WHITE_LO, _WHITE_HI

_STREET = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


def card_present(corner_bgr):
    """True if a face-up card occupies this corner crop (mostly bright card-face)."""
    if not _HAVE:
        raise RuntimeError("vision needs numpy + opencv")
    g = cv2.cvtColor(corner_bgr, cv2.COLOR_BGR2GRAY)
    white = cv2.inRange(cv2.cvtColor(corner_bgr, cv2.COLOR_BGR2HSV), _WHITE_LO, _WHITE_HI)
    return float(white.mean()) / 255.0 > 0.55 and float(g.mean()) > 140


def _corner(frame, x, y, cfg):
    cw, ch = cfg["corner"]
    return frame[y:y + ch, x:x + cw]


def board_count(frame, cfg):
    """Number of community cards currently dealt (0/3/4/5)."""
    return sum(card_present(_corner(frame, x, y, cfg))
               for x, y in cfg["board"]
               if _corner(frame, x, y, cfg).shape[:2] == (cfg["corner"][1], cfg["corner"][0]))


def street(frame, cfg):
    """Street name from the board: preflop / flop / turn / river (or 'N board')."""
    n = board_count(frame, cfg)
    return _STREET.get(n, f"{n} board")
