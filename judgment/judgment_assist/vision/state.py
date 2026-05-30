"""Classify a captured frame into a coarse game state.

Used to sort the 'watch me play' screenshot library (capture/dataset.py) so a
card detector trains only on card-bearing frames, while the other states are
kept and labeled for their own uses.

States:
  decision  — action menu up (Hit/Stand/Double/[Split]/Surrender). BEST for card
              detection: the hand is fully laid out and you're choosing.
  in_hand   — hand in progress, cards on the felt, no menu, no modal. Also good
              for card detection.
  modal     — a centered dialog dims the table: betting screen ("Chips/Wagered",
              bet limit) OR end-of-hand result ("Blackjack Result", win/lose).
              Not used for card training; kept for outcome / round-boundary use.
  other     — transitions / anything unmatched.

Thresholds were MEASURED on hand-labeled frames (not guessed). Clean separators
found:
  * menu blue-highlight fraction: decision 2.4-5.1%, everything else 0.0%
  * corner brightness (modal dimming): playing 70-80, modal up 52-58
The earlier result-vs-betting split was fuzzy on these features, so both fold
into ``modal`` — the distinction that matters for training (cards vs no-cards)
is the clean one.
"""
from __future__ import annotations

DECISION, IN_HAND, MODAL, OTHER = "decision", "in_hand", "modal", "other"

# tuned from measured feature distributions (see module docstring)
_BLUE_MENU = 1.5       # >this -> action menu highlighted -> decision
_CORNER_DIM = 65       # corner mean V <this -> a modal overlay is dimming the table
_CARDS_MIN = 4.0       # felt cream-pixel % above this -> cards are on the table


def _features(img, reader, dealer_roi, player_roi):
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    dx, dy, dw, dh = dealer_roi
    px, py, pw, ph = player_roi
    _dv, dconf = reader.read(img[dy:dy + dh, dx:dx + dw])
    _pv, pconf = reader.read(img[py:py + ph, px:px + pw])

    # action-menu highlighted button: saturated blue in the left button column
    menu = hsv[60:250, 100:440]
    blue = ((menu[:, :, 0] > 95) & (menu[:, :, 0] < 130) &
            (menu[:, :, 1] > 120) & (menu[:, :, 2] > 120))
    blue_pct = 100.0 * float(blue.mean())

    # corner brightness: a modal overlay darkens the whole table (incl. corners)
    cs = 120
    corner_v = float(np.mean([
        gray[:cs, :cs].mean(), gray[:cs, -cs:].mean(),
        gray[-cs:, :cs].mean(), gray[-cs:, -cs:].mean(),
    ]))

    # cards on the felt: cream/bright low-saturation pixels in the table area
    felt = hsv[120:760, 250:1700]
    cards_pct = 100.0 * float(((felt[:, :, 2] > 160) & (felt[:, :, 1] < 80)).mean())

    return dict(dconf=dconf, pconf=pconf, blue=blue_pct,
                corner=corner_v, cards=cards_pct)


def classify(img, reader, dealer_roi, player_roi):
    """Return ``(state, features)``. ``reader`` is a HudReader; the ROIs are the
    HUD badge boxes from regions.json."""
    f = _features(img, reader, dealer_roi, player_roi)

    if f["blue"] > _BLUE_MENU:
        return DECISION, f                       # action menu is up
    if f["corner"] < _CORNER_DIM:
        return MODAL, f                          # a dialog is dimming the table
    if f["cards"] > _CARDS_MIN:
        return IN_HAND, f                        # cards out, table bright, no menu
    return OTHER, f


def is_card_frame(state):
    """True for states a card detector should train on."""
    return state in (DECISION, IN_HAND)
