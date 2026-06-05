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
  poker     — SEMI-AUTO. The loop auto-reads the pot, street, active-opponent
              count and to_call, and auto-DETECTS your hole cards (best-effort —
              card reading is the documented ~80% wall, POKER.md, so it's a guess:
              suit colour is reliable, rank/exact-suit are not). You confirm (bare
              Enter) or correct the hand by typing; a typed hand locks until the next
              deal. Every confirmation/correction is saved as a new labeled exemplar
              and hot-added to the reader, so it LEARNS as you play (``--no-learn``
              to disable). Shows equity + pot-odds + a call/raise/fold call. Needs
              the ``poker`` ROIs, the white-glyph poker digit templates
              (``--poker-digits``), the labeled corner crops for detection
              (``--poker-cards``; ``--no-detect`` to type manually).
"""
from __future__ import annotations

import argparse
import json
import os
import time

from ..cards import card_str, cards_str, parse_cards, INT_TO_RANK
from ..capture.screen import ScreenGrabber
from ..capture.window import find_window_region
from ..poker.advisor import decide as poker_decide
from ..poker.equity import equity as poker_equity
from ..poker.evaluator import evaluate7, category_name


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


class CardInput:
    """Background stdin reader that forwards parsed card entries to a ``target``
    (the :class:`PokerAdvisor`). The hero confirms/corrects the auto-detected
    hand and types the board as it develops; this thread owns stdin.

        Enter (blank)        confirm the detected hand (locks it; saves training)
        Ah Kh                set/correct your hole cards (locks the auto-detect)
        Ah Kh | Qh 7h 2h     set hole + board
        | Qh 7h 2h           update the board only (keep hole)
        + Td                 deal one more board card (turn / river)
        c                    clear -> hand back to auto-detect    q  quit
    """

    def __init__(self, target, start=True):
        import threading
        self.target, self.stop = target, False
        self._threading = threading
        if start:
            self.start_thread()

    def start_thread(self):
        """Read card commands from stdin on a daemon thread (console mode)."""
        self._threading.Thread(target=self._loop, daemon=True).start()

    def apply(self, line):
        """Apply one input line by calling the target. Returns False on quit, else
        True. Raises ValueError on unparseable cards (the loop keeps going).
        Cards are parsed before the target is touched, so a typo changes nothing."""
        line = line.strip()
        if not line:                                   # bare Enter -> confirm
            self.target.confirm()
            return True
        if line.lower() in ("q", "quit", "exit"):
            self.stop = True
            return False
        if line.lower() in ("c", "clear"):
            self.target.clear()
        elif line.startswith("+"):                     # deal one more board card
            self.target.append_board(parse_cards(line[1:]))
        elif "|" in line:                              # hole | board
            h, b = line.split("|", 1)
            board = parse_cards(b) if b.strip() else []
            hole = parse_cards(h) if h.strip() else None
            if hole is not None:
                self.target.set_hole(hole)
            self.target.set_board(board)
        else:                                          # hole only -> preflop
            self.target.set_hole(parse_cards(line))
            self.target.set_board([])
        return True

    def _loop(self):
        import sys
        for line in sys.stdin:
            try:
                if not self.apply(line):
                    break
            except Exception as e:  # noqa: BLE001 - keep the input loop alive
                print("  bad cards:", e)


class PokerAdvisor:
    """Semi-auto poker advice. Auto-reads the table state (pot / street / active
    opponents / to_call) every frame and **auto-detects the hero's hole cards**,
    which the hero confirms or corrects by typing. Card reading is the documented
    ~80% wall (POKER.md), so a detected hand is a *guess* shown for correction:
    suit colour is reliable, rank/exact-suit are not. A typed hand locks until the
    hand ends (hole slots empty -> next deal re-detects). Monte-Carlo equity is
    cached so only the cheap pot-odds decision recomputes per frame.

    Card state is owned here (not in CardInput) so detection and the hero's typed
    override share one source of truth; the stdin thread mutates it under a lock."""

    def __init__(self, reader, cfg, opp_fallback=2, iters=12000, card_reader=None,
                 training=None):
        import threading
        self.reader, self.cfg = reader, cfg
        self.opp_fallback, self.iters = opp_fallback, iters
        self.card_reader = card_reader
        self.training = training          # TrainingWriter or None (learn off)
        self._lock = threading.Lock()
        self.hole, self.board, self.hole_locked = [], [], False
        self._info = None                 # per-hole detection info (colour, conf)
        self._present_last = False        # were both hole slots up last frame?
        self._cand, self._cand_n = None, 0   # stability filter for detection
        self._good_frame = None           # last LIVE (cards-present) frame, for capture
        self._key = self._eq = None

    # -- hero input (called from the CardInput thread) ------------------------
    def set_hole(self, cards):
        with self._lock:
            self.hole, self.hole_locked, self._info = list(cards), True, None
        self._capture(self.cfg.get("hole", []), cards, "H")   # corrected/confirmed

    def set_board(self, cards):
        with self._lock:
            self.board = list(cards)
        self._capture(self.cfg.get("board", []), cards, "B")

    def append_board(self, cards):
        with self._lock:
            self.board = self.board + list(cards)
        self._capture(self.cfg.get("board", []), self.board, "B")

    def confirm(self):
        """Bare-Enter: accept the current detected hand as correct — lock it and
        save it as training data (the cases the reader got right)."""
        with self._lock:
            hole, locked = list(self.hole), self.hole_locked
            if len(hole) == 2 and not locked:
                self.hole_locked = True
        if len(hole) == 2 and not locked:
            self._capture(self.cfg.get("hole", []), hole, "H")

    def clear(self):
        with self._lock:
            self.hole, self.board, self.hole_locked = [], [], False
            self._info, self._cand, self._cand_n = None, None, 0

    # -- training capture ----------------------------------------------------
    def _capture(self, anchors, cards, prefix):
        """Save each face-up card's WHOLE-card crop with its (now-known) label as a
        new exemplar, and hot-add it to the live reader. Captures from the last
        LIVE frame (cards present) — NOT the current one, which may be the
        dimmed/paused screen if you tabbed to the console to type. No-op when
        learning is off."""
        if self.training is None:
            return
        from ..vision.poker import card_present
        from ..vision.poker_cards import whole_roi
        with self._lock:
            frame = self._good_frame
        if frame is None:
            return
        cw, ch = self.cfg["corner"]
        saved = []
        for i, card in enumerate(cards):
            if i >= len(anchors):
                break
            x, y = anchors[i]
            corner = frame[y:y + ch, x:x + cw]
            if corner.shape[:2] != (ch, cw) or not card_present(corner):
                continue
            l, t, w, h = whole_roi((x, y), f"{prefix}{i}")
            whole = frame[t:t + h, l:l + w]
            if whole.shape[:2] != (h, w):
                continue
            rank, suit = card
            if self.training.save(whole, rank, suit, f"{prefix}{i}"):
                if self.card_reader is not None:
                    self.card_reader.add_exemplar(whole, rank, suit)
                saved.append(card_str(card))
        if saved:
            print(f"  + learned {' '.join(saved)} ({len(saved)} new crop(s))")

    # -- auto detection ------------------------------------------------------
    def _hole_present(self, frame):
        """Both hole slots showing a bright, face-up card (gated on the corner —
        a dimmed/paused screen reads as not-present, which is what we want)."""
        from ..vision.poker import card_present
        cw, ch = self.cfg["corner"]
        hole = self.cfg.get("hole", [])
        if not hole:
            return False
        for x, y in hole:
            c = frame[y:y + ch, x:x + cw]
            if c.shape[:2] != (ch, cw) or not card_present(c):
                return False
        return True

    def _detect(self, frame, present):
        """Update the hole cards from the screen unless the hero has typed them.
        Reads the WHOLE card (better than the corner); re-detects at each new deal
        (hole slots empty -> up); a 2-frame stability filter avoids a half-deal."""
        from ..vision.poker_cards import whole_roi
        if present and not self._present_last:        # a new hand was dealt
            with self._lock:
                self.hole_locked, self.board = False, []
                self._cand, self._cand_n = None, 0
        if present and not self.hole_locked:
            reads = []
            for i, (x, y) in enumerate(self.cfg["hole"]):
                l, t, w, h = whole_roi((x, y), f"H{i}")
                reads.append(self.card_reader.recognize(frame[t:t + h, l:l + w]))
            det = tuple(card for card, _ in reads)
            self._cand_n = self._cand_n + 1 if det == self._cand else 1
            self._cand = det
            if self._cand_n >= 2:                      # stable -> accept the guess
                with self._lock:
                    if not self.hole_locked:
                        self.hole = list(det)
                        self._info = [info for _, info in reads]
        self._present_last = present

    def _equity(self, hole, board, opp):
        key = (tuple(hole), tuple(board), opp)
        if key != self._key:
            eq = poker_equity(hole, board, opponents=opp, iters=self.iters)
            if len(board) >= 3:
                eq["made_hand"] = category_name(evaluate7(list(hole) + list(board)))
            self._eq, self._key = eq, key
        return self._eq

    def text(self, frame):
        from ..vision import poker as P
        # Cache the last LIVE frame (hole cards present) for training capture, so a
        # correction typed while the game is paused/tabbed-away uses good pixels.
        present = self._hole_present(frame) if (self.card_reader or self.training) else False
        if present:
            with self._lock:
                self._good_frame = frame
        if self.card_reader is not None:
            self._detect(frame, present)
        with self._lock:
            hole, board = list(self.hole), list(self.board)
            locked, info = self.hole_locked, self._info

        st = P.table_state(frame, self.cfg, self.reader)
        pot, to_call = st["pot"] or 0, st["to_call"]
        # The street comes from the board the hero TYPED (authoritative), not the
        # screen's board count — in semi-auto mode they can disagree mid-deal.
        stage = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(
            len(board), f"{len(board)} cards")
        # auto opponent count from the fold banners; fall back to --opp if the
        # banners aren't calibrated (opp_active empty).
        n_auto = st["n_active"] if st["opp_active"] else None
        opp = n_auto if n_auto is not None else self.opp_fallback
        opp_src = "active" if n_auto is not None else "set"
        live = f"POT {pot}  {stage.upper()}  vs {opp} {opp_src}  to-call {to_call}"
        if len(hole) != 2:
            hint = "type your hole cards  e.g.  Ah Kh" if self.card_reader is None \
                else "waiting for your hole cards (deal in)..."
            return f"poker: {hint}\n" + live
        dupes = len(set(hole) | set(board)) != len(hole) + len(board)
        if dupes:
            return f"poker: duplicate card in {cards_str(hole)} / {cards_str(board)}\n" + live
        if opp < 1:
            return f"YOU {cards_str(hole)} - all opponents folded, pot is yours\n" + live
        # A detected (not yet confirmed) hand is a guess — flag it and show the
        # reliable colour so the hero can correct rank/suit at a glance.
        tag = ""
        if not locked:
            cols = "/".join(i["color"] for i in info) if info else ""
            tag = f"  (detected {cols} - type to fix)"
        out = poker_decide(self._equity(hole, board, opp), to_call=to_call, pot=pot)
        made = f"  [{out['made_hand']}]" if "made_hand" in out else ""
        odds = f"  pot-odds {out['pot_odds']*100:.0f}%" if to_call > 0 else ""
        return (f"YOU {cards_str(hole)}{made}{tag}\n"
                f"BRD {cards_str(board) or '-'} ({stage})\n"
                f"{live}\n"
                f">>> {out['recommendation'].upper()}  eq {out['equity']*100:.0f}%{odds}")


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
    cards_in = poker = None
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
        # Semi-auto poker: we auto-read pot / street / opponents / to_call and
        # auto-DETECT the hero's hole cards (best-effort — card reading is the
        # documented ~80% wall, POKER.md), shown for the hero to confirm/correct.
        from ..vision.hud import HudReader
        reader = HudReader(a.poker_digits, min_confidence=a.min_confidence)
        card_reader = training = None
        if not a.no_detect:
            try:
                from ..vision.poker_cards import HoleCardReader
                card_reader = HoleCardReader(a.poker_cards)
            except RuntimeError as e:
                print(f"  (hole-card auto-detect off — {e})")
        if a.learn:
            try:
                from ..vision.poker_cards import TrainingWriter
                training = TrainingWriter(a.poker_cards)
                print(f"  learning ON - confirmed/corrected cards saved to {a.poker_cards}")
            except RuntimeError as e:
                print(f"  (learning off — {e})")
        poker = PokerAdvisor(reader, roi_cfg, opp_fallback=a.opp, iters=a.iters,
                             card_reader=card_reader, training=training)
        cards_in = CardInput(poker, start=False)   # wired to the overlay box (or stdin if --no-overlay)

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

    def step(frame):
        """One frame -> the overlay text (plus blackjack's per-frame side effects:
        hand tracking, DB rows, counting, miss-saving)."""
        nonlocal hand_no, last_result, miss_streak, miss_saved
        # The game window collapses to 0x0 when minimized/not foreground; mss then
        # returns an empty frame. Don't read it — wait.
        if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
            return f"{a.game}: game window not visible (focus Judgment)..."
        if a.game != "blackjack":
            return poker.text(frame)
        card_reads = read_clusters(frame, rank_rec) if rank_rec is not None else None
        pt = dealer_up = None
        if result_reader is not None or shoe is not None or misses_dir:
            pt, _ = reader.read_roi(frame, roi_cfg["player_total"])
            dealer_up, _ = reader.read_roi(frame, roi_cfg["dealer_total"])
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
        return text

    overlay = None
    if not a.no_overlay:
        from .overlay import SuggestionOverlay
        hint = ("Advice updates live - just play. To FIX a card: click the box below,\n"
                "type it (e.g. As Kd), Enter.  Click the game window to keep playing.\n"
                "Enter on a correct hand banks it for training.  | Qh 7c 2d = board   "
                "+ Td = deal   c = clear.  Close this window (or type q) to stop."
                ) if a.game == "poker" else ""
        overlay = SuggestionOverlay(x=a.x, y=a.y, input_enabled=(a.game == "poker"),
                                    hint=hint)
        if a.game == "poker":
            def _on_submit(line):
                if not cards_in.apply(line):    # 'q' -> stop
                    overlay.request_close()
            overlay.on_submit = _on_submit

    print(f"live {a.game} advisor running. overlay={'off' if a.no_overlay else 'on'}"
          + ("" if overlay else " (Ctrl-C to stop)"))
    try:
        with ScreenGrabber(monitor=monitor) as g:
            if overlay is not None:
                # tkinter-driven: the overlay owns the loop, so its input box stays
                # responsive. We just re-read the screen on a timer.
                interval_ms = max(50, int(a.interval * 1000))

                def tick():
                    if overlay.closed:
                        return
                    overlay.update_text(step(g.grab(resolve_base(cfg))))
                    overlay.root.after(interval_ms, tick)

                overlay.root.after(0, tick)
                overlay.root.mainloop()
            else:
                # console mode: print advice; poker reads cards from stdin.
                if a.game == "poker":
                    cards_in.start_thread()
                while not (cards_in is not None and cards_in.stop):
                    print("\n" + step(g.grab(resolve_base(cfg))))
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
    p.add_argument("--templates", default="data/templates", help="card templates (blackjack felt)")
    p.add_argument("--digits", default="data/digits", help="digit templates (blackjack HUD)")
    p.add_argument("--poker-digits", dest="poker_digits", default="data/poker_digits",
                   help="white-glyph digit templates for the poker pot/bet plates")
    p.add_argument("--poker-cards", dest="poker_cards", default="data/poker_cards",
                   help="labeled corner crops used to auto-detect hole cards (advisory)")
    p.add_argument("--no-detect", dest="no_detect", action="store_true",
                   help="disable hole-card auto-detection (type all cards manually)")
    p.add_argument("--no-learn", dest="learn", action="store_false",
                   help="don't save confirmed/corrected cards as new training data")
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
    p.add_argument("--opp", type=int, default=3,
                   help="opponents to assume for equity when the active count can't "
                        "be read (Judgment poker is 4-handed: you + 3)")
    p.add_argument("--iters", type=int, default=12000)
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
