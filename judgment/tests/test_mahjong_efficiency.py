import pytest

from judgment_assist.mahjong.efficiency import (
    best_discard,
    discard_options,
    ukeire,
)
from judgment_assist.mahjong.tiles import parse_hand, tile_index

H = parse_hand


def test_ukeire_tanki_wait():
    # 4 melds + a lone 9s: only another 9s (3 left) completes the pair
    accepts, total = ukeire(H("123m 456m 789m 123p 9s"))
    nines = tile_index(9, "s")
    assert accepts == [(nines, 3)]
    assert total == 3


def test_ukeire_respects_seen_tiles():
    seen = [0] * 34
    seen[tile_index(9, "s")] = 2  # two 9s already gone elsewhere
    accepts, total = ukeire(H("123m 456m 789m 123p 9s"), seen=seen)
    assert total == 1  # 4 - 1 in hand - 2 seen


def test_ryanmen_beats_kanchan_in_ukeire():
    # ryanmen 56m accepts 4m+7m (8 tiles); discarding to keep it should win out
    accepts, total = ukeire(H("56m 123p 456p 789p 99s"))
    assert {t for t, _ in accepts} == {tile_index(4, "m"), tile_index(7, "m")}
    assert total == 8


def test_discard_options_sorted_best_first():
    opts = discard_options(H("123m 456m 789m 123p 99s"))
    assert opts[0]["shanten"] == 0           # already a won hand; any cut -> tenpai
    sh = [o["shanten"] for o in opts]
    assert sh == sorted(sh)                    # non-decreasing shanten


def test_best_discard_keeps_the_ryanmen():
    # 3 melds + pair + ryanmen (tenpai shape) with one isolated floater (1z).
    # The advisor must cut the floater, not break the 56m ryanmen.
    hand = H("56m 99m 456p 789p 123s 1z")
    best = best_discard(hand)
    assert best["tile"] == tile_index(1, "z")
    assert best["shanten"] == 0


def test_discard_requires_14_tile_hand():
    with pytest.raises(ValueError):
        discard_options(H("123m 456m 789m 123p 9s"))  # 13 tiles
