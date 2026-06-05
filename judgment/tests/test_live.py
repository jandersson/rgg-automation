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
def test_card_input_sets_hole_and_board():
    ci = CardInput(start=False)
    ci.apply("Ah Kh")                       # hole only -> preflop
    assert ci.get() == (parse_cards("Ah Kh"), [])
    ci.apply("Ah Kh | Qh 7h 2h")            # hole + board
    assert cards_str(ci.get()[1]) == "Qh 7h 2h"


def test_card_input_append_and_board_only():
    ci = CardInput(start=False)
    ci.apply("Ah Kh | Qh 7h 2h")
    ci.apply("+ Td")                         # deal the turn, keep hole+flop
    hole, board = ci.get()
    assert cards_str(hole) == "Ah Kh" and cards_str(board) == "Qh 7h 2h Td"
    ci.apply("| Qh 7h 2h Td Js")             # update board only, hole untouched
    assert cards_str(ci.get()[0]) == "Ah Kh"
    assert cards_str(ci.get()[1]) == "Qh 7h 2h Td Js"


def test_card_input_bad_cards_leave_state_intact():
    ci = CardInput(start=False)
    ci.apply("Ah Kh")
    with pytest.raises(ValueError):
        ci.apply("Zz Kh")                    # typo -> raises, state unchanged
    assert cards_str(ci.get()[0]) == "Ah Kh"


def test_card_input_quit():
    ci = CardInput(start=False)
    assert ci.apply("q") is False and ci.stop is True


class _FakeReader:
    """Stand-in HudReader: returns a value per ROI key (poker section uses string
    keys for the number ROIs so the fake can map them)."""
    def __init__(self, vals):
        self.vals = vals

    def read_roi(self, frame, roi, white=False):
        return self.vals.get(roi), 1.0


def _poker_cfg():
    # board ROIs land on dealt felt; banners are blank (all active). String keys
    # for the number ROIs let _FakeReader resolve them.
    return {"corner": [70, 105],
            "board": [[296, 298], [562, 298], [838, 298], [1128, 298], [1410, 298]],
            "pot": "pot", "bet": "my",
            "opp_bet": ["o0", "o1", "o2"],
            "opp_banner": [[0, 0, 95, 42], [100, 0, 95, 42], [200, 0, 95, 42]]}


def _felt_with_board(n):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    f = np.full((1080, 1920, 3), (70, 120, 40), np.uint8)
    for x, y in _poker_cfg()["board"][:n]:
        f[y:y + 200, x - 4:x + 180] = (245, 245, 245)
    return f


def test_poker_advisor_prompts_without_hole_cards():
    reader = _FakeReader({"pot": 40, "my": 0, "o0": 20, "o1": 20, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=2000)
    txt = pa.text(_felt_with_board(0), [], [])
    assert "type your hole cards" in txt
    assert "to-call 20" in txt and "vs 3 active" in txt    # auto-read still shown


def test_poker_advisor_full_advice_uses_autoread_state():
    # flop, hero owes 5 to call into a 20 pot vs 3 active opponents
    reader = _FakeReader({"pot": 20, "my": 15, "o0": 20, "o1": 20, "o2": 20})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=4000)
    txt = pa.text(_felt_with_board(3), parse_cards("Ac As"), parse_cards("Ah Kd 9s"))
    assert "vs 3 active" in txt and "to-call 5" in txt
    assert "three of a kind" in txt and ">>> RAISE" in txt


def test_poker_advisor_flags_duplicate_cards():
    reader = _FakeReader({"pot": 20, "my": 0, "o0": 0, "o1": 0, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=2000)
    txt = pa.text(_felt_with_board(3), parse_cards("Ah Kd"), parse_cards("Ah 2c 3d"))
    assert "duplicate card" in txt


def test_poker_advisor_caches_equity_across_frames():
    reader = _FakeReader({"pot": 20, "my": 0, "o0": 0, "o1": 0, "o2": 0})
    pa = PokerAdvisor(reader, _poker_cfg(), iters=4000)
    f = _felt_with_board(3)
    pa.text(f, parse_cards("Ac As"), parse_cards("Ah Kd 9s"))
    first = pa._eq
    pa.text(f, parse_cards("Ac As"), parse_cards("Ah Kd 9s"))
    assert pa._eq is first                                  # same cards -> not recomputed


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
