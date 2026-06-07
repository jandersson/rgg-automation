from judgment_assist.mahjong.shanten import (
    chiitoitsu_shanten,
    is_complete,
    kokushi_shanten,
    shanten,
    standard_shanten,
)
from judgment_assist.mahjong.tiles import parse_hand

H = parse_hand


# ------------------------------------------------------------------ standard ---
def test_standard_complete_hand_is_minus_one():
    assert is_complete(H("123m 456m 789m 123p 99s"))
    assert standard_shanten(H("123m 456m 789m 123p 99s")) == -1


def test_standard_tenpai():
    # 4 melds done, waiting on the pair (tanki on 9s)
    assert standard_shanten(H("123m 456m 789m 123p 9s")) == 0
    # three melds + pair + ryanmen, waiting 3m/6m
    assert standard_shanten(H("45m 123p 456p 789p 99s")) == 0


def test_standard_one_shanten():
    # three melds, a pair, and a floating tile that must pair or extend
    assert standard_shanten(H("123m 456m 789m 99p 3s")) == 1


def test_nine_gates_is_tenpai():
    # pure nine gates: any man tile completes it -> tenpai
    assert shanten(H("1112345678999m")) == 0


# ---------------------------------------------------------------- chiitoitsu ---
def test_chiitoitsu_complete_only_via_seven_pairs():
    # non-consecutive pairs: no runs/triplets possible, so only chiitoi wins
    hand = H("11m 88m 11p 88p 11s 88s 11z")
    assert chiitoitsu_shanten(hand) == -1
    assert is_complete(hand)


def test_chiitoitsu_tenpai_and_duplicates_dont_count():
    assert chiitoitsu_shanten(H("11m 22m 33p 44p 55s 66s 7s")) == 0
    # a triplet only gives one pair toward chiitoi (kinds matters)
    assert chiitoitsu_shanten(H("111m 22m 33p 44p 55s 66s")) == 1


# ------------------------------------------------------------------- kokushi ---
def test_kokushi_tenpai_thirteen_wait():
    assert kokushi_shanten(H("19m 19p 19s 1234567z")) == 0


def test_kokushi_complete():
    hand = H("19m 19p 19s 1234567z 1z")  # East paired
    assert kokushi_shanten(hand) == -1
    assert is_complete(hand)


# ---------------------------------------------------------------- aggregate ----
def test_shanten_takes_the_best_form():
    # this 13-tile hand is closer via chiitoi than standard
    hand = H("11m 33m 55p 77p 99s 22z 4z")
    assert shanten(hand) == min(
        standard_shanten(hand), chiitoitsu_shanten(hand), kokushi_shanten(hand)
    )
