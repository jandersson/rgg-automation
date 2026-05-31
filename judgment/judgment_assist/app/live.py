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
              and the digit templates in ``data/digits``. Also keeps a Hi-Lo
              count by reading the felt cards each frame (``ShoeCounter``, needs
              the rank templates in ``data/templates``); the running/true count
              feeds count-aware strategy and bet sizing. ``--no-count`` disables.
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
    # Insurance is +EV only at a high true count (dealer Ace up); flag it then.
    ins = "  [TAKE INSURANCE]" if (dealer == 11 and true_count is not None
                                   and true_count >= 3) else ""
    return (f"YOU {player}   DEALER {dlabel}\n"
            f">>> {dec.action.upper()}  ({dec.reason}){note}{ins}")


def count_line(shoe):
    """One-line Hi-Lo readout for the overlay."""
    last = f"  last:{shoe.last_outcome}" if shoe.last_outcome else ""
    return (f"COUNT  RC {shoe.running:+d}  TC {shoe.true_count:+.1f}"
            f"  ({shoe.seen} cards, {shoe.hands} hands){last}  bet {shoe.bet_units()}u")


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
    # blackjack reads the HUD "Total" badges (config section 'hud'); poker reads
    # cards (section 'poker').
    section = "hud" if a.game == "blackjack" else a.game
    roi_cfg = cfg.get(section)
    if not roi_cfg:
        raise SystemExit(f"no '{section}' section in {a.config} — "
                         f"run calibration first (mark --game {section})")

    rank_rec = shoe = read_ranks = result_reader = None
    if a.game == "blackjack":
        from ..vision.hud import HudReader
        reader = HudReader(a.digits, min_confidence=a.min_confidence)
        # Optional card counting: read ranks off the felt and keep a Hi-Lo count.
        # Advice still works without it (totals come from the HUD), so missing
        # templates just disable counting rather than failing the run.
        if not a.no_count:
            from ..vision.recognizer import CardRecognizer
            from ..vision.reader import read_ranks as _read_ranks
            from ..blackjack.counting import ShoeCounter
            try:
                rank_rec = CardRecognizer(a.templates, mode="rank",
                                          min_confidence=a.min_confidence)
                shoe = ShoeCounter(decks=a.decks)
                read_ranks = _read_ranks
            except RuntimeError as e:
                print(f"  (card counting off — {e})")
            # Result-banner reader gives a definitive hand boundary + outcome.
            try:
                from ..vision.result import ResultReader
                result_reader = ResultReader(a.results)
            except RuntimeError as e:
                print(f"  (result-cue detection off — {e})")
    else:
        from ..vision.recognizer import CardRecognizer
        reader = CardRecognizer(a.templates, mode="card", min_confidence=a.min_confidence)

    overlay = None
    if not a.no_overlay:
        from .overlay import SuggestionOverlay
        overlay = SuggestionOverlay(x=a.x, y=a.y)

    monitor = cfg.get("monitor", 1)
    prev_cue = None  # last frame's result banner, for rising-edge hand-end detection
    print(f"live {a.game} advisor running (Ctrl-C to stop). overlay={'off' if a.no_overlay else 'on'}")
    try:
        with ScreenGrabber(monitor=monitor) as g:
            while True:
                base = resolve_base(cfg)
                frame = g.grab(base)
                # The game window collapses to 0x0 when minimized/not foreground;
                # mss then returns an empty frame. Don't read it — wait.
                if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
                    text = f"{a.game}: game window not visible (focus Judgment)..."
                elif a.game == "blackjack":
                    if result_reader is not None and shoe is not None:
                        cue = result_reader.read(frame)
                        if cue and cue != prev_cue:   # banner just appeared -> hand ended
                            shoe.end_hand(cue)
                        prev_cue = cue
                    if shoe is not None:
                        shoe.observe(read_ranks(frame, rank_rec))
                    text = blackjack_text(reader, frame, roi_cfg,
                                          shoe.true_count if shoe else None)
                    if shoe is not None:
                        text += "\n" + count_line(shoe)
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
    # blackjack counting
    p.add_argument("--decks", type=int, default=6, help="shoe size for true-count scaling")
    p.add_argument("--results", default="data/results",
                   help="result-banner templates (Win/Lose/Push/Blackjack)")
    p.add_argument("--no-count", action="store_true",
                   help="disable Hi-Lo card counting (advice only)")
    # poker
    p.add_argument("--opp", type=int, default=2)
    p.add_argument("--iters", type=int, default=12000)
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
