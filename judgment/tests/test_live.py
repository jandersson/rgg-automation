"""Tests for the live advisor's player-hand identification + full-strategy upgrade."""
import pytest

from judgment_assist.app.live import (match_player_hand, log_hand, HandTracker,
                                      CardInput, PokerAdvisor)
from judgment_assist.blackjack.counting import ShoeCounter
from judgment_assist.blackjack.strategy import recommend, DOUBLE, SPLIT
from judgment_assist.cards import parse_cards, cards_str


def test_match_player_hand_picks_cluster_matching_total():
    # player cluster 6+5=11, dealer cluster shows a 10
    assert match_player_hand([[6, 5], [10]], 11) == [6, 5]


def test_match_player_hand_handles_soft_total():
    # A,6 is soft 17 -> total 17
    assert match_player_hand([[14, 6]], 17) == [14, 6]


def test_match_player_hand_none_when_nothing_matches():
    assert match_player_hand([[6, 5]], 20) is None
    assert match_player_hand(None, 11) is None
    assert match_player_hand([], 11) is None


def test_match_player_hand_merges_split_clusters():
    # the real bug: a 10 and a 9 read as two separate clusters; neither equals 19
    assert match_player_hand([[10], [9]], 19) == [10, 9]
    # a split pair must still recognise the pair (drives SPLIT)
    assert match_player_hand([[8], [8]], 16) == [8, 8]
    # soft hand split across clusters
    assert match_player_hand([[14], [6]], 17) == [14, 6]


def test_match_player_hand_drops_stray_cluster():
    # 10+9 = 19; a stray 5 cluster (noise/other) is excluded via the subset search
    assert match_player_hand([[10], [9], [5]], 19) == [10, 9]


def test_matched_hand_drives_double_and_split_advice():
    # the whole point: a confirmed 2-card hand unlocks DOUBLE / SPLIT
    hand = match_player_hand([[6, 5], [10]], 11)         # 11 vs dealer 10
    assert recommend(hand, 10).action == DOUBLE
    pair8 = match_player_hand([[8, 8], [7]], 16)          # pair of 8s
    assert recommend(pair8, 7).action == SPLIT


def test_blackjack_text_hand_over_not_rereading():
    from judgment_assist.app.live import blackjack_text

    class FR:   # fake HUD reader returning fixed totals by ROI key
        def __init__(self, d, p): self.d, self.p = d, p
        def read_roi(self, frame, roi): return (self.d, 1.0) if roi == "D" else (self.p, 1.0)

    roi = {"dealer_total": "D", "player_total": "P"}
    # result frame: the dealer drew out to 20 -> "hand over", NEVER "re-reading"
    t = blackjack_text(FR(20, 18), None, roi)
    assert "re-reading" not in t and "hand over" in t and "DEALER 20" in t
    assert "BUST" in blackjack_text(FR(10, 24), None, roi)          # player bust flagged
    advice = blackjack_text(FR(6, 16), None, roi)                    # live decision still advises
    assert ">>>" in advice and "DEALER 6" in advice


def test_hand_tracker_dedupes_bust_and_keeps_upcard():
    # the real DB bug: a busted hand logged BUST/BUST/LOSE (3x) for one hand, and
    # dealer_up was the dealer's FINAL total (22), not the up-card (6).
    t = HandTracker()
    seq = [(14, 6, None),       # in-play, dealer up-card 6
           (20, 6, None),       # player hit, still in-play
           (24, 22, "BUST"),    # busted: HUD>21, dealer revealed to 22, BUST banner
           (24, 22, "BUST"),    # lingering result frame
           (24, 22, "LOSE")]    # banner switches to LOSE — same hand
    events = [e for e in (t.update(p, d, c) for p, d, c in seq) if e is not None]
    assert events == [("BUST", 6)]        # exactly one event; up-card 6, not 22


def test_hand_tracker_rearms_each_new_hand():
    t = HandTracker()
    assert t.update(18, 10, None) is None
    assert t.update(18, 10, "LOSE") == ("LOSE", 10)   # hand 1 result
    assert t.update(18, 10, "LOSE") is None            # lingering -> no dupe
    assert t.update(15, 7, None) is None               # new hand in-play -> re-arm
    assert t.update(15, 7, "WIN") == ("WIN", 7)        # hand 2 result


def test_hand_tracker_skips_hand_not_watched_from_play():
    # overlay restarted mid-round, landing on the result phase -> never saw the
    # play (or the dealer up-card), so the hand must NOT be logged.
    t = HandTracker()
    assert t.update(20, 20, "PUSH") is None
    assert t.update(20, 20, "PUSH") is None
    # the next hand, observed from its play phase, logs normally
    assert t.update(17, 8, None) is None
    assert t.update(17, 8, "WIN") == ("WIN", 8)


# ----------------------------------------------------- semi-auto poker input --
def test_card_input_forwards_hole_and_board_to_target():
    pa = PokerAdvisor(reader=None, cfg={})
    ci = CardInput(pa, start=False)
    ci.apply("Ah Kh")                       # hole only -> preflop, locks
    assert pa.hole == parse_cards("Ah Kh") and pa.board == [] and pa.hole_locked
    ci.apply("Ah Kh | Qh 7h 2h")            # hole + board
    assert cards_str(pa.board) == "Qh 7h 2h"


def test_card_input_append_and_board_only():
    pa = PokerAdvisor(reader=None, cfg={})
    ci = CardInput(pa, start=False)
    ci.apply("Ah Kh | Qh 7h 2h")
    ci.apply("+ Td")                         # deal the turn, keep hole+flop
    assert cards_str(pa.hole) == "Ah Kh" and cards_str(pa.board) == "Qh 7h 2h Td"
    ci.apply("| Qh 7h 2h Td Js")             # update board only, hole untouched
    assert cards_str(pa.hole) == "Ah Kh"
    assert cards_str(pa.board) == "Qh 7h 2h Td Js"


def test_card_input_clear_and_quit():
    pa = PokerAdvisor(reader=None, cfg={})
    ci = CardInput(pa, start=False)
    ci.apply("Ah Kh")
    ci.apply("c")                            # clear -> back to auto-detect
    assert pa.hole == [] and not pa.hole_locked
    assert ci.apply("q") is False and ci.stop is True


def test_card_input_bad_cards_leave_state_intact():
    pa = PokerAdvisor(reader=None, cfg={})
    ci = CardInput(pa, start=False)
    ci.apply("Ah Kh")
    with pytest.raises(ValueError):
        ci.apply("Zz Kh")                    # typo -> raises, state unchanged
    assert cards_str(pa.hole) == "Ah Kh"


class _FakeReader:
    """Stand-in HudReader: returns a value per ROI key (poker section uses string
    keys for the number ROIs so the fake can map them)."""
    def __init__(self, vals):
        self.vals = vals

    def read_roi(self, frame, roi, white=False):
        return self.vals.get(roi), 1.0


def _poker_cfg():
    # hole and board rows are SEPARATE (as in the real game) so painting the hole
    # for detection doesn't inflate the screen board count. String keys for the
    # number ROIs let _FakeReader resolve them; banners blank => all active.
    return {"corner": [70, 105],
            "hole": [[652, 650], [984, 650]],
            "board": [[296, 298], [562, 298], [838, 298], [1128, 298], [1410, 298]],
            "pot": "pot", "bet": "my",
            "opp_bet": ["o0", "o1", "o2"],
            "opp_banner": [[0, 0, 95, 42], [100, 0, 95, 42], [200, 0, 95, 42]]}


def _frame(n_board=0, hole=True):
    """A felt frame with both hole cards face-up (for detection/presence) and the
    first ``n_board`` community cards dealt (sets the screen street)."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    f = np.full((1080, 1920, 3), (70, 120, 40), np.uint8)
    cfg = _poker_cfg()
    slots = (cfg["hole"] if hole else []) + cfg["board"][:n_board]
    for x, y in slots:
        f[y:y + 200, x - 4:x + 180] = (245, 245, 245)
    return f


def test_poker_advisor_prompts_without_hole_cards():
    reader = _FakeReader({"pot": 40, "my": 0, "o0": 20, "o1": 20, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=2000)     # no card_reader -> manual
    txt = pa.text(_frame(0, hole=False))
    assert "type your hole cards" in txt
    assert "to-call 20" in txt and "vs 3 active" in txt    # auto-read still shown


def test_poker_advisor_full_advice_uses_autoread_state():
    # flop, hero owes 5 to call into a 20 pot vs 3 active opponents
    reader = _FakeReader({"pot": 20, "my": 15, "o0": 20, "o1": 20, "o2": 20})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=4000)
    pa.set_hole(parse_cards("Ac As"))
    pa.set_board(parse_cards("Ah Kd 9s"))
    txt = pa.text(_frame(3))
    assert "vs 3 active" in txt and "to-call 5" in txt
    assert "three of a kind" in txt and ">>> RAISE" in txt


def test_poker_advisor_street_follows_screen_and_prompts_for_board():
    # screen shows 3 community cards but you've only typed your hole -> show FLOP
    # and ask for the board, not stale preflop odds.
    reader = _FakeReader({"pot": 80, "my": 0, "o0": 0, "o1": 0, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=2000)
    pa.set_hole(parse_cards("Ah Kh"))
    txt = pa.text(_frame(3))                  # 3 board cards visible, none typed
    assert "FLOP" in txt and "type the board" in txt
    pa.set_board(parse_cards("Qh 7c 2d"))     # now type them -> real advice, flop
    txt2 = pa.text(_frame(3))
    assert "(flop)" in txt2 and ">>>" in txt2 and "type the board" not in txt2


def test_confirm_hotkey_vk_map():
    from judgment_assist.app.live import _VK
    assert _VK["f13"] == 0x7C and _VK["f24"] == 0x87   # F13-F24 for the back button
    assert "home" in _VK and "f1" in _VK


def test_screen_dimmed_detects_pause():
    np = pytest.importorskip("numpy")
    live = np.full((100, 100, 3), 90, np.uint8)
    paused = np.full((100, 100, 3), 20, np.uint8)
    from judgment_assist.app.live import _screen_dimmed
    assert _screen_dimmed(paused) is True and _screen_dimmed(live) is False


def test_poker_advisor_flags_duplicate_cards():
    reader = _FakeReader({"pot": 20, "my": 0, "o0": 0, "o1": 0, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=2000)
    pa.set_hole(parse_cards("Ah Kd"))
    pa.set_board(parse_cards("Ah 2c 3d"))
    assert "duplicate card" in pa.text(_frame(3))


def test_poker_advisor_caches_equity_across_frames():
    reader = _FakeReader({"pot": 20, "my": 0, "o0": 0, "o1": 0, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=4000)
    pa.set_hole(parse_cards("Ac As"))
    pa.set_board(parse_cards("Ah Kd 9s"))
    f = _frame(3)
    pa.text(f)
    first = pa._eq
    pa.text(f)
    assert pa._eq is first                                  # same cards -> not recomputed


class _FakeCardReader:
    """Stand-in HoleCardReader: returns the two given (card, info) pairs in
    alternation (one per corner), so each frame reads the same two cards."""
    def __init__(self, hole, board=()):
        self.hole, self.board = list(hole), list(board)
        self.h, self.b, self.added = 0, 0, []

    def set_pair(self, hole):
        self.hole = list(hole)               # simulate the screen showing new hole cards

    def set_board_cards(self, board):
        self.board = list(board)             # simulate new community cards

    def recognize(self, corner_bgr, kind="H"):
        if kind == "H":
            self.b = 0                       # a frame is read hole-first, then board
            r = self.hole[self.h % len(self.hole)]
            self.h += 1
            return r
        r = self.board[self.b]
        self.b += 1
        return r

    def add_exemplar(self, corner_bgr, rank, suit):
        self.added.append((rank, suit))


class _RecWriter:
    """Records what would be saved as training data (rank, suit, slot)."""
    def __init__(self):
        self.saved = []

    def save(self, corner_bgr, rank, suit, slot):
        self.saved.append((cards_str([(rank, suit)]), slot))
        return True


def test_poker_advisor_autodetects_hole_then_locks_on_override():
    reader = _FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0})
    det = ((parse_cards("Ac")[0], {"color": "black"}),
           (parse_cards("Kd")[0], {"color": "red"}))
    pa = PokerAdvisor(reader, _poker_cfg(), iters=2000,
                      card_reader=_FakeCardReader(det))
    f = _frame(0)                  # both hole slots show a face-up card
    pa.text(f)                               # 1st frame: candidate, not yet stable
    assert pa.hole == []
    txt = pa.text(f)                         # 2nd identical frame: accept the guess
    assert cards_str(pa.hole) == "Ac Kd" and not pa.hole_locked
    assert "(detected black/red - type to fix)" in txt
    pa.set_hole(parse_cards("Ah Kh"))        # hero corrects -> locks, detection stops
    pa.text(f)
    assert cards_str(pa.hole) == "Ah Kh" and pa.hole_locked


def test_poker_advisor_captures_correction_as_training():
    w = _RecWriter()
    pa = PokerAdvisor(_FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, training=w)
    pa.text(_frame(0))             # both hole slots face-up, frame cached
    pa.set_hole(parse_cards("Ah Kd"))        # correction -> saved with your labels
    assert w.saved == [("Ah", "H0"), ("Kd", "H1")]


def test_poker_advisor_confirm_saves_detected_hand():
    det = ((parse_cards("Ac")[0], {"color": "black"}),
           (parse_cards("Kd")[0], {"color": "red"}))
    cr, w = _FakeCardReader(det), _RecWriter()
    pa = PokerAdvisor(_FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, card_reader=cr, training=w)
    f = _frame(0)
    pa.text(f); pa.text(f)                    # detect -> hole set (unlocked)
    pa.confirm()                              # bare Enter -> lock + save detected
    assert w.saved == [("Ac", "H0"), ("Kd", "H1")] and pa.hole_locked
    assert len(cr.added) == 2                 # hot-added to the live reader too


def test_confirm_banks_detected_board_too():
    cr, w = _FakeCardReader(_det("Ac", "Kd"), _seq("Qh", "7c", "2d")), _RecWriter()
    pa = PokerAdvisor(_FakeReader({"pot": 40, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, card_reader=cr, training=w)
    pa.text(_frame(3)); pa.text(_frame(3))    # hole + board auto-detected
    pa.confirm()                              # Enter banks BOTH hole and board
    slots = [slot for _, slot in w.saved]
    assert slots == ["H0", "H1", "B0", "B1", "B2"]


def test_poker_advisor_captures_typed_board():
    w = _RecWriter()
    pa = PokerAdvisor(_FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, training=w)
    pa.text(_frame(3))
    pa.set_board(parse_cards("Qh 7h 2h"))    # typed board cards are labels too
    assert [slot for _, slot in w.saved] == ["B0", "B1", "B2"]


def test_poker_advisor_no_capture_when_learning_off():
    pa = PokerAdvisor(_FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, training=None)   # learn off
    pa.text(_frame(0))
    pa.set_hole(parse_cards("Ah Kd"))        # no writer -> no crash, just sets state
    assert cards_str(pa.hole) == "Ah Kd"


def _det(c0, c1):
    return ((parse_cards(c0)[0], {"color": "black"}), (parse_cards(c1)[0], {"color": "red"}))


def _seq(*cards):
    return [(parse_cards(c)[0], {"color": "black"}) for c in cards]


def test_poker_advisor_autodetects_board():
    cr = _FakeCardReader(_det("Ac", "Kd"), _seq("Qh", "7c", "2d"))
    pa = PokerAdvisor(_FakeReader({"pot": 40, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, card_reader=cr)
    f = _frame(3)                             # hole present + 3 community cards
    pa.text(f); pa.text(f)                    # stabilise
    assert cards_str(pa.hole) == "Ac Kd"
    assert cards_str(pa.board) == "Qh 7c 2d"  # board auto-detected too


def test_typed_board_card_held_while_new_card_autodetects():
    cr = _FakeCardReader(_det("Ac", "Kd"), _seq("Qh", "7c", "2d"))
    pa = PokerAdvisor(_FakeReader({"pot": 40, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, card_reader=cr)
    pa.text(_frame(3)); pa.text(_frame(3))            # flop auto-detected: Qh 7c 2d
    pa.set_board(parse_cards("Qh 7c 2s"))             # hero fixes the 3rd card
    cr.set_board_cards(_seq("Qh", "7c", "2d", "Td"))  # turn dealt (4th card)
    pa.text(_frame(4)); pa.text(_frame(4))
    assert cards_str(pa.board) == "Qh 7c 2s Td"       # fix kept, new card auto-filled


def test_correction_survives_pause_resume_same_hand():
    # the reported bug: type a fix, pause (cards read as absent), resume -> the
    # SAME cards reappear, which must NOT wipe the correction.
    cr = _FakeCardReader(_det("4s", "9h"))
    pa = PokerAdvisor(_FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, card_reader=cr)
    f = _frame(0)
    pa.text(f); pa.text(f)                    # detect 4s 9h, baseline = 4s 9h
    pa.set_hole(parse_cards("8c 2d"))         # hero corrects -> locked
    pa.text(_frame(0, hole=False))              # pause: hole reads as absent
    pa.text(f); pa.text(f); pa.text(f)        # resume: same 4s 9h on screen
    assert pa.hole_locked and cards_str(pa.hole) == "8c 2d"   # correction kept


def test_poker_advisor_redetects_after_new_deal():
    cr = _FakeCardReader(_det("7c", "2d"))
    pa = PokerAdvisor(_FakeReader({"pot": 0, "my": 0, "o0": 0, "o1": 0, "o2": 0}),
                      _poker_cfg(), iters=2000, card_reader=cr)
    f = _frame(0)
    pa.text(f); pa.text(f)                    # detect 7c 2d, baseline = 7c 2d
    pa.set_hole(parse_cards("Ah Kh"))         # correction -> locked
    pa.text(f)
    assert pa.hole_locked and cards_str(pa.hole) == "Ah Kh"   # same hand -> kept
    cr.set_pair(_det("As", "Kd"))             # a genuinely NEW hand is dealt
    pa.text(f); pa.text(f); pa.text(f)        # 3 stable frames of the new read
    assert not pa.hole_locked and cards_str(pa.hole) == "As Kd"   # re-detected


def test_log_hand_writes_a_csv_row(tmp_path):
    sc = ShoeCounter(confirm=1)
    sc.observe([5, 6])          # +2, two cards
    sc.end_hand("WIN")
    p = tmp_path / "sessions" / "hands.csv"   # parent dir does not exist yet
    log_hand(str(p), sc)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "time,hand,outcome,running,true_count,cards_seen"
    fields = lines[1].split(",")
    assert fields[1] == "1" and fields[2] == "WIN" and fields[3] == "2" and fields[5] == "2"
