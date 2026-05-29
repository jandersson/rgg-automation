"""Live advisor loop: capture -> recognise -> advise -> overlay.

    py -m judgment_assist.app.live blackjack
    py -m judgment_assist.app.live poker --opp 3

Reads ``config/regions.json`` (built with the calibration tool) and the card
templates in ``data/templates``. If ``regions.json`` names a ``window`` we
re-resolve that window's client area every frame (robust to moving the window);
otherwise we grab the configured ``monitor`` whole. ROIs are stored relative to
whichever base is captured, so calibration and runtime stay consistent.

Advice-only by design — it never sends inputs to the game.

Current scope:
  blackjack — reads your hand + dealer up card -> basic strategy / Six-Card
              Charlie advice. (Auto card-counting across hands is future work;
              use the manual CLI's `seen` for counting today.)
  poker     — reads hole + board -> equity & made hand vs ``--opp`` opponents.
              Pot-odds need chip-count OCR (future); use the manual CLI for the
              precise call/fold line.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from ..cards import card_str, INT_TO_RANK
from ..vision.recognizer import CardRecognizer
from ..capture.screen import ScreenGrabber
from ..capture.window import find_window_region
from ..blackjack.engine import BlackjackAdvisor, Rules
from ..blackjack.strategy import hand_total
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


def _ranks_str(cards):
    return " ".join(INT_TO_RANK[c[0]] for c in cards)


def blackjack_text(rec, frame, roi_cfg, advisor):
    up = rec.recognize_many(frame, [roi_cfg["dealer_upcard"]])
    hand = rec.recognize_many(frame, roi_cfg.get("player_cards", []))
    if not hand or not up:
        return "blackjack: waiting for cards..."
    ranks = [c[0] for c in hand]
    total, soft = hand_total(ranks)
    dec = advisor.advise(ranks, up[0][0])
    return (f"YOU {_ranks_str(hand)} = {total}{' soft' if soft else ''}\n"
            f"DLR {INT_TO_RANK[up[0][0]]}\n"
            f">>> {dec.action.upper()}  ({dec.reason})")


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

    rec = CardRecognizer(a.templates, min_confidence=a.min_confidence)
    advisor = BlackjackAdvisor(Rules(decks=a.decks, hit_soft_17=a.h17)) if a.game == "blackjack" else None

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
                    text = blackjack_text(rec, frame, roi_cfg, advisor)
                else:
                    text = poker_text(rec, frame, roi_cfg, a.opp, a.iters)
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
    p.add_argument("--templates", default="data/templates")
    p.add_argument("--interval", type=float, default=0.7, help="seconds between reads")
    p.add_argument("--min-confidence", dest="min_confidence", type=float, default=0.6)
    p.add_argument("--no-overlay", action="store_true", help="print to console instead")
    p.add_argument("--x", type=int, default=40)
    p.add_argument("--y", type=int, default=40)
    # blackjack
    p.add_argument("--decks", type=int, default=6)
    p.add_argument("--h17", action="store_true")
    # poker
    p.add_argument("--opp", type=int, default=2)
    p.add_argument("--iters", type=int, default=12000)
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
