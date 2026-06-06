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


# ------------------------------------------------------- folded opponents -----
# A player who folds keeps a "Fold" action banner under their plate for the rest
# of the hand, marked by a distinctive CYAN double-chevron icon. Every other
# action uses a non-cyan icon (Call = green, Raise = red, Check/Bet/blinds), and
# the felt behind the banner is duller and greener (H~84, S~104) than the icon
# (H~102, S~180). So counting saturated-cyan pixels in the icon box separates
# folded from active cleanly — across a full 697-frame session the count was
# <=1 for every non-fold banner and 150-250 for every fold (no overlap). This is
# label-free, like the rest of this module.
_CYAN_LO = (92, 140, 85)
_CYAN_HI = (112, 255, 255)
_FOLD_CYAN_MIN = 50          # px; real folds ~150-250, everything else <=1


def opp_folded(banner_bgr):
    """True if this opponent's action-banner crop is a 'Fold' (cyan-chevron icon)."""
    if not _HAVE:
        raise RuntimeError("vision needs numpy + opencv")
    if banner_bgr is None or banner_bgr.size == 0:
        return False
    cyan = cv2.inRange(cv2.cvtColor(banner_bgr, cv2.COLOR_BGR2HSV), _CYAN_LO, _CYAN_HI)
    return int(cyan.sum() // 255) >= _FOLD_CYAN_MIN


def _roi(frame, roi):
    l, t, w, h = roi
    return frame[t:t + h, l:l + w]


def opp_active(frame, cfg):
    """Per-opponent active (not folded) flags, read from the action banners.

    Empty if the config has no ``opp_banner`` ROIs (uncalibrated) — callers then
    fall back to a manual opponent count."""
    return [not opp_folded(_roi(frame, b)) for b in cfg.get("opp_banner", [])]


# ------------------------------------------------------------- to-call --------
def to_call(opp_bets, active, my_bet):
    """Chips it costs the hero to call: the highest current-round bet among the
    still-active opponents, minus what the hero has already put in this round
    (never negative; 0 means it's free to check).

    A folded opponent never holds the max current bet, so masking to ``active``
    can't lower the result vs. taking the max over everyone — but it does drop a
    stale/garbage read sitting on a folded seat, and keeps the semantics honest.
    ``None`` entries (unreadable plates) are skipped."""
    live = [b for b, a in zip(opp_bets, active) if a and b is not None]
    if not live:
        return 0
    return max(0, max(live) - (my_bet or 0))


def read_opp_bets(frame, cfg, reader):
    """Current-round Bet of each opponent (``None`` where the plate won't read).

    ``reader`` is a ``vision.hud.HudReader`` built on the poker digit templates;
    the poker plates are white glyphs on a coloured panel, so we read with
    ``white=True``. Empty if the config has no ``opp_bet`` ROIs (uncalibrated)."""
    return [reader.read_roi(frame, roi, white=True)[0] for roi in cfg.get("opp_bet", [])]


def table_state(frame, cfg, reader):
    """Everything the semi-auto overlay auto-reads from one frame: pot, street,
    each opponent's current bet + active flag, the hero's own bet, the count of
    still-active opponents, and the resulting to-call. Cards are NOT read here —
    the hero types those (poker card reading is the documented ~80% wall)."""
    n = board_count(frame, cfg)
    bets = read_opp_bets(frame, cfg, reader)
    active = opp_active(frame, cfg)
    my_bet = reader.read_roi(frame, cfg["bet"], white=True)[0]
    pot = reader.read_roi(frame, cfg["pot"], white=True)[0]
    # The central pot plate only holds chips SWEPT from previous streets — it reads
    # 0 preflop, because this round's bets still sit in front of each player (their
    # Bet plates). Pot odds must price the call against the whole contested pot, so
    # ``pot_total`` adds the live bets (everyone's, folded included — it's all dead
    # money the winner takes). This stays continuous across the street sweep: when
    # the bets reset to 0 the pot plate rises by the same amount, so the total
    # doesn't jump. Without it the advisor saw pot 0 preflop -> pot-odds 100% ->
    # folded even premium hands.
    committed = (my_bet or 0) + sum(b for b in bets if b is not None)
    return {
        "pot": pot,
        "committed": committed,
        "pot_total": (pot or 0) + committed,
        "board": n,
        "street": _STREET.get(n, f"{n} board"),
        "opp_bets": bets,
        "opp_active": active,
        "n_active": sum(active),
        "my_bet": my_bet,
        "to_call": to_call(bets, active, my_bet),
    }
