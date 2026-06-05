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
              gives hit/stand advice. To upgrade that to double/split/soft it
              also reads the player's own felt cards (needs the rank templates in
              ``data/templates``); if they're missing it falls back to totals.
              Needs the ``hud`` ROIs (calibrate mark --game hud) and the digit
              templates in ``data/digits``. Hi-Lo counting is EXPERIMENTAL and
              OFF by default (``--count``): this is a multi-seat table, so the
              reader can't see most of the shoe and the count isn't usable for
              betting (issue #3). The HUD-total advice is the reliable product.
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


def _insurance(dealer, true_count):
    # Insurance is +EV only at a high true count, on a dealer Ace up.
    return ("  [TAKE INSURANCE]" if (dealer == 11 and true_count is not None
                                     and true_count >= 3) else "")


def match_player_hand(card_reads, total):
    """The player's hand among the read clusters, identified and validated via
    the reliable HUD total. Returns the matching ranks, or None (→ totals-only).

    The localizer routinely SPLITS one hand into several single-card clusters
    when the cards are spaced rather than tightly cascaded (e.g. a 10 and a 9
    sitting apart read as ``[[10], [9]]``, neither of which equals 19), so we
    can't just compare each cluster to the total. The play-area gate already
    excludes the other seats, so the in-frame clusters are the player's own
    cards: we look for the combination of clusters whose combined blackjack total
    equals the HUD total, preferring the one that uses the MOST clusters (the
    whole hand). A lone noise/dealer cluster is dropped by trying smaller subsets."""
    from itertools import combinations
    from ..blackjack.strategy import hand_total
    clusters = [c for c in (card_reads or []) if c]
    for k in range(len(clusters), 0, -1):       # most clusters first = whole hand
        for combo in combinations(clusters, k):
            ranks = [r for c in combo for r in c]
            if hand_total(ranks)[0] == total:
                return ranks
    return None


def blackjack_text(reader, frame, roi_cfg, true_count=None, card_reads=None):
    """Advise from the HUD totals, upgraded to full strategy (double / split /
    soft) when the player's actual cards are read and confirm the total."""
    from ..blackjack.strategy import recommend_hard, recommend

    dealer, _dc = reader.read_roi(frame, roi_cfg["dealer_total"])
    player, _pc = reader.read_roi(frame, roi_cfg["player_total"])
    if dealer is None or player is None:
        return "blackjack: waiting for a decision (totals not visible)..."
    if player > 21:
        return f"YOU {player} — BUST"
    if dealer >= 12:
        # During play the dealer shows only an up-card (2-11); a total of 12+ means
        # the dealer has revealed/drawn -> the hand is resolved, nothing to advise.
        # (The caller appends the LAST: outcome line.) NOT a misread.
        return f"YOU {player}   DEALER {dealer}  (hand over)"
    if dealer < 2:
        return f"blackjack: dealer total {dealer}? (re-reading)"
    dlabel = "A" if dealer == 11 else str(dealer)
    hand = match_player_hand(card_reads, player)
    if hand is not None:
        # cards confirmed -> full strategy: knows soft/pair/2-card, can say DOUBLE/SPLIT
        dealer_rank = 14 if dealer == 11 else dealer  # value -> a rank of that value
        dec = recommend(hand, dealer_rank, true_count=true_count)
        cards = " ".join(INT_TO_RANK[r] for r in hand)
        return (f"YOU {player} [{cards}]   DEALER {dlabel}\n"
                f">>> {dec.action.upper()}  ({dec.reason}){_insurance(dealer, true_count)}")
    # cards not cleanly read -> totals only; can't see soft/pair/whether 2-card
    dec = recommend_hard(player, dealer, true_count=true_count)
    note = "  (!) if soft/pair/2-card, verify" if player <= 20 else ""
    return (f"YOU {player}   DEALER {dlabel}\n"
            f">>> {dec.action.upper()}  ({dec.reason}){note}{_insurance(dealer, true_count)}")


def count_line(shoe):
    """One-line Hi-Lo readout. EXPERIMENTAL / UNRELIABLE: this is a multi-seat
    table — other players' and the dealer's cards sit at the edges, angled and
    often clipped off-frame, so they can't be read. The count therefore misses
    most of the shoe and must NOT be used for betting; it's shown for dev only."""
    last = f"  last:{shoe.last_outcome}" if shoe.last_outcome else ""
    return (f"COUNT(exp/unreliable)  RC {shoe.running:+d}  TC {shoe.true_count:+.1f}"
            f"  ({shoe.seen} cards, {shoe.hands} hands){last}")


def log_hand(path, shoe):
    """Append one CSV row per finished hand — the data to answer 'persistent shoe?'
    (does the running count drift and hold across hands, or reset each hand?)."""
    import datetime
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("time,hand,outcome,running,true_count,cards_seen\n")
        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')},{shoe.hands},"
                f"{shoe.last_outcome},{shoe.running},{shoe.true_count:.2f},{shoe.seen}\n")


class HandTracker:
    """Turns the per-frame stream of (player_total, dealer_total, result_cue) into
    exactly ONE event per finished hand.

    Three things it gets right that naive per-frame logging didn't:
    * **Only log hands we watched from the start.** ``in_hand`` flips True when we
      see the play phase (a readable in-play total, no result), and a hand is only
      logged if it's set. So a mid-round restart that lands on the result phase is
      skipped — we don't record a hand whose play (and dealer up-card) we never saw.
    * **Dedup.** A busted hand shows HUD>21 for several frames AND then a result
      banner. ``in_hand`` clears on the first result frame, so the rest don't re-log
      until the next hand's play re-arms it.
    * **Dealer up-card.** At the result the dealer badge shows the dealer's FINAL
      total (e.g. 22), not the up-card. We remember the dealer total seen DURING
      play (when only the up-card is exposed, value 2-11) and report that."""

    def __init__(self):
        self.in_hand = False        # have we observed this hand's play phase?
        self.dealer_upcard = None

    def update(self, player_total, dealer_total, cue):
        """Return ``(outcome, dealer_upcard)`` once, on the first result frame of a
        hand we watched from play; otherwise ``None``."""
        busted = player_total is not None and player_total > 21
        result_now = bool(cue) or busted
        if not result_now and player_total is not None and 2 <= player_total <= 21:
            self.in_hand = True                       # watching an active hand
            if dealer_total is not None and 2 <= dealer_total <= 11:
                self.dealer_upcard = dealer_total     # only the up-card is shown now
            return None
        if result_now and self.in_hand:               # gate: must have seen the play
            self.in_hand = False
            up = self.dealer_upcard
            self.dealer_upcard = None
            return (cue or "BUST", up)
        return None


def save_miss(dirpath, frame, hud_total, card_reads):
    """Dump a frame where the read disagrees with the HUD total — a reader miss.
    The filename records both totals so the failures are easy to triage later."""
    import cv2
    import datetime
    os.makedirs(dirpath, exist_ok=True)
    reads = "-".join("".join(INT_TO_RANK[r] for r in cl) for cl in card_reads if cl) or "none"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    cv2.imwrite(os.path.join(dirpath, f"miss_{ts}_hud{hud_total}_read{reads}.png"), frame)


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

    rank_rec = shoe = read_clusters = result_reader = None
    store = session_id = None
    if a.game == "blackjack":
        from ..vision.hud import HudReader
        reader = HudReader(a.digits, min_confidence=a.min_confidence)
        # Read the player's own cards off the felt to upgrade the advice to
        # double/split/soft. Advice still works without it (HUD totals only), so
        # missing templates just disable the upgrade. This is INDEPENDENT of
        # counting — the reader earns its keep on advice regardless.
        try:
            from ..vision.recognizer import CardRecognizer
            from ..vision.reader import read_clusters as _read_clusters
            rank_rec = CardRecognizer(a.templates, mode="rank",
                                      min_confidence=a.min_confidence)
            read_clusters = _read_clusters
        except RuntimeError as e:
            print(f"  (card reading off — {e})")
        # Hi-Lo counting is EXPERIMENTAL and OFF by default. This is a multi-seat
        # table: the other players' and dealer's cards sit at the edges, outside
        # the reader, so the count only ever sees a fraction of the shoe and is
        # NOT usable for betting (issue #3 — and only matters at all if the game
        # runs a persistent shoe, which is unconfirmed). --count enables it for dev.
        # The result-banner reader gives definitive hand boundaries + outcomes,
        # needed by BOTH counting and DB session logging.
        db_on = bool(a.db) and not a.no_db
        # The result-banner reader powers the last-result overlay line, the DB hand
        # boundaries, and counting — always build it for blackjack.
        try:
            from ..vision.result import ResultReader
            result_reader = ResultReader(a.results)
        except RuntimeError as e:
            print(f"  (result-cue detection off — {e})")
        if a.count and rank_rec is not None:
            from ..blackjack.counting import ShoeCounter
            shoe = ShoeCounter(decks=a.decks)
        if db_on:
            from ..sessions import SessionStore
            store = SessionStore(a.db)
            session_id = store.start_session("blackjack", config=a.config)
            print(f"  tracking hands to session {session_id} in {a.db}")
    else:
        from ..vision.recognizer import CardRecognizer
        reader = CardRecognizer(a.templates, mode="card", min_confidence=a.min_confidence)

    overlay = None
    if not a.no_overlay:
        from .overlay import SuggestionOverlay
        overlay = SuggestionOverlay(x=a.x, y=a.y)

    monitor = cfg.get("monitor", 1)
    tracker = HandTracker()   # one event per hand (dedup) + the dealer up-card
    hand_no = 0               # per-session finished-hand counter (for the DB)
    last_result = None        # last finished-hand outcome, shown in the overlay
    log_path = a.log if a.game == "blackjack" else None
    misses_dir = a.save_misses if a.game == "blackjack" else None
    miss_streak, miss_saved = 0, False
    if log_path:
        print(f"  logging each hand to {log_path}")
    if misses_dir:
        print(f"  saving reader-miss frames to {misses_dir}")
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
                    # read the felt once: per-cluster for strategy, flattened for counting
                    card_reads = read_clusters(frame, rank_rec) if rank_rec is not None else None
                    # HUD totals: needed for bust detection, the DB row, and miss-saving.
                    pt = dealer_up = None
                    if result_reader is not None or shoe is not None or misses_dir:
                        pt, _ = reader.read_roi(frame, roi_cfg["player_total"])
                        dealer_up, _ = reader.read_roi(frame, roi_cfg["dealer_total"])
                    # One event per finished hand (dedupes the bust cue + banner),
                    # carrying the dealer up-card seen during play.
                    cue = result_reader.read(frame) if result_reader is not None else None
                    event = tracker.update(pt, dealer_up, cue)
                    if event is not None:
                        outcome, dealer_upcard = event
                        last_result = outcome
                        hand_no += 1
                        if shoe is not None and shoe.end_hand(outcome) and log_path:
                            log_hand(log_path, shoe)
                        if store is not None:
                            store.record_hand(
                                session_id, hand_no, outcome=outcome,
                                player_total=pt, dealer_up=dealer_upcard,
                                running=shoe.running if shoe else None,
                                true_count=shoe.true_count if shoe else None,
                                cards_seen=shoe.seen if shoe else None)
                    if shoe is not None:
                        shoe.observe([r for cl in (card_reads or []) for r in cl])
                    # save frames where the read disagrees with the HUD total (reader
                    # misses) for later analysis — only sustained mismatches, once each
                    if misses_dir and card_reads and pt is not None and 2 <= pt <= 21:
                        if match_player_hand(card_reads, pt) is None:
                            miss_streak += 1
                            if miss_streak == 3 and not miss_saved:
                                save_miss(misses_dir, frame, pt, card_reads)
                                miss_saved = True
                        else:
                            miss_streak, miss_saved = 0, False
                    text = blackjack_text(reader, frame, roi_cfg,
                                          shoe.true_count if shoe else None, card_reads)
                    if last_result is not None:
                        text += f"\nLAST: {last_result}"
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
        if store is not None:
            store.close_session(session_id)
            store.close()
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
                   help="result-banner templates (Win/Lose/Push/Blackjack/Bust)")
    p.add_argument("--count", action="store_true",
                   help="EXPERIMENTAL: enable Hi-Lo card counting (off by default — "
                        "multi-seat table, the count can't see most of the shoe; issue #3)")
    p.add_argument("--db", default="data/sessions/sessions.db",
                   help="SQLite DB for session/hand logging (blackjack; ON by default, "
                        "one session per run, one row per finished hand). "
                        "Analyse with `-m judgment_assist.app.sessions`")
    p.add_argument("--no-db", action="store_true", help="disable session DB logging")
    p.add_argument("--log", default=None,
                   help="append a CSV row per finished hand (outcome + running/true count)")
    p.add_argument("--save-misses", dest="save_misses", default=None,
                   help="dir to dump frames where the card read disagrees with the HUD total")
    # poker
    p.add_argument("--opp", type=int, default=2)
    p.add_argument("--iters", type=int, default=12000)
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
