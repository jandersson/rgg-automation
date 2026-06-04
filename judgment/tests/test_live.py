"""Tests for the live advisor's player-hand identification + full-strategy upgrade."""
from judgment_assist.app.live import match_player_hand, log_hand
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
