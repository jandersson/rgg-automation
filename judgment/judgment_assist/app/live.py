"""Live advisor loop: capture -> recognise -> advise -> overlay.

    py -m judgment_assist.app.live blackjack
    py -m judgment_assist.app.live poker --opp 3

Reads ``config/regions.json`` (built with the calibration tool). If
``regions.json`` names a ``window`` we re-resolve that window's client area every
frame (robust to moving the window); otherwise we grab the configured
``monitor`` whole. ROIs are stored relative to whichever base is captured, so
calibration and runtime stay consistent.

Advice-only by design — it never sends inputs to the game.

Current scope:
  blackjack — reads the two HUD "Total" badges (dealer up + player total) and
              gives hit/stand advice. Totals alone can't tell soft hands, pairs,
              or whether a double is still legal, so the overlay flags those for
              a manual check. Needs the ``hud`` ROIs (calibrate mark --game hud)
              and the digit templates in ``data/digits``.
  poker     — reads hole + board cards via template matching -> equity & made
              hand vs ``--opp`` opponents. Needs card templates + ``poker`` ROIs.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from ..cards import card_str, INT_TO_RANK
from ..capture.screen import ScreenGrabber
from ..capture.window import find_window_region
from ..poker.advisor import advise as poker_advise


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_base(cfg):
    """Return the capture base region dict, or None for the whole monitor."""
    title = cfg.get("window")
    if title:
        reg = find_window_region(title)
        if reg is None:
            return None  # window not found right now; fall back to monitor
        return reg
    return None


def blackjack_text(reader, frame, roi_cfg, true_count=None):
    """Read the two HUD badges and advise from totals."""
    from ..blackjack.strategy import recommend_hard

    dealer, dconf = reader.read_roi(frame, roi_cfg["dealer_total"])
    player, pconf = reader.read_roi(frame, roi_cfg["player_total"])
    if dealer is None or player is None:
        return "blackjack: waiting for a decision (totals not visible)..."
    if not (2 <= dealer <= 11):
        return f"blackjack: dealer total {dealer}? (re-reading)"
    if player > 21:
        return f"YOU {player} — BUST"
    dec = recommend_hard(player, dealer, true_count=true_count)
    dlabel = "A" if dealer == 11 else str(dealer)
    note = "  (!) if soft/pair, verify" if player <= 20 else ""
    return (f"YOU {player}   DEALER {dlabel}\n"
            f">>> {dec.action.upper()}  ({dec.reason}){note}")


def poker_text(rec, frame, roi_cfg, opponents, iters):
    hole = rec.recognize_many(frame, roi_cfg.get("hole_cards", []))
    board = rec.recognize_many(frame, roi_cfg.get("board_cards", []))
    if len(hole) < 2:
        return "poker: waiting for hole cards..."
    out = poker_advise(hole, board, opponents=opponents, iters=iters)
    made = f"  [{out['made_hand']}]" if "made_hand" in out else ""
    stage = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(board), f"{len(board)}")
    return (f"YOU {card_str(hole[0])} {card_str(hole[1])}{made}\n"
            f"BRD {' '.join(card_str(c) for c in board) or '-'} ({stage})\n"
            f">>> {out['recommendation'].upper()}  eq {out['equity']*100:.0f}% vs {opponents}")


def run(a):
    cfg = load_config(a.config)
    roi_cfg = cfg.get(a.game)
    if not roi_cfg:
        raise SystemExit(f"no '{a.game}' section in {a.config} — run calibration first")

    if a.game == "blackjack":
        from ..vision.hud import HudReader
        reader = HudReader(a.digits, min_confidence=a.min_confidence)
    else:
        from ..vision.recognizer import CardRecognizer
        reader = CardRecognizer(a.templates, mode="card", min_confidence=a.min_confidence)

    overlay = None
    if not a.no_overlay:
        from .overlay import SuggestionOverlay
        overlay = SuggestionOverlay(x=a.x, y=a.y)

    monitor = cfg.get("monitor", 1)
    print(f"live {a.game} advisor running (Ctrl-C to stop). overlay={'off' if a.no_overlay else 'on'}")
    try:
        with ScreenGrabber(monitor=monitor) as g:
            while True:
                base = resolve_base(cfg)
                frame = g.grab(base)
                if a.game == "blackjack":
                    text = blackjack_text(reader, frame, roi_cfg)
                else:
                    text = poker_text(reader, frame, roi_cfg, a.opp, a.iters)
                if overlay:
                    overlay.update_text(text)
                else:
                    print("\n" + text)
                time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        if overlay:
            overlay.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist live")
    p.add_argument("game", choices=["blackjack", "poker"])
    p.add_argument("--config", default="config/regions.json")
    p.add_argument("--templates", default="data/templates", help="card templates (poker)")
    p.add_argument("--digits", default="data/digits", help="digit templates (blackjack HUD)")
    p.add_argument("--interval", type=float, default=0.7, help="seconds between reads")
    p.add_argument("--min-confidence", dest="min_confidence", type=float, default=0.6)
    p.add_argument("--no-overlay", action="store_true", help="print to console instead")
    p.add_argument("--x", type=int, default=40)
    p.add_argument("--y", type=int, default=40)
    # poker
    p.add_argument("--opp", type=int, default=2)
    p.add_argument("--iters", type=int, default=12000)
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
