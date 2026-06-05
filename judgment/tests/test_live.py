"""Tests for the live advisor's player-hand identification + full-strategy upgrade."""
from judgment_assist.app.live import match_player_hand, log_hand, HandTracker
from judgment_assist.blackjack.counting import ShoeCounter
from judgment_assist.blackjack.strategy import recommend, DOUBLE, SPLIT


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
