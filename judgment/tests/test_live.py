"""Tests for the live advisor's player-hand identification + full-strategy upgrade."""
from judgment_assist.app.live import match_player_hand
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


def test_matched_hand_drives_double_and_split_advice():
    # the whole point: a confirmed 2-card hand unlocks DOUBLE / SPLIT
    hand = match_player_hand([[6, 5], [10]], 11)         # 11 vs dealer 10
    assert recommend(hand, 10).action == DOUBLE
    pair8 = match_player_hand([[8, 8], [7]], 16)          # pair of 8s
    assert recommend(pair8, 7).action == SPLIT
