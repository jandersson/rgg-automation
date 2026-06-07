import pytest

from judgment_assist.mahjong.tiles import (
    format_hand,
    hand_size,
    is_terminal_or_honor,
    parse_hand,
    tile_index,
    tile_name,
)


def test_tile_index_layout():
    assert tile_index(1, "m") == 0
    assert tile_index(9, "m") == 8
    assert tile_index(1, "p") == 9
    assert tile_index(1, "s") == 18
    assert tile_index(1, "z") == 27   # East
    assert tile_index(7, "z") == 33   # Red dragon


def test_tile_name_roundtrip():
    for idx in range(34):
        r, suit = (idx % 9) + 1, "mpsz"[idx // 9]
        assert tile_name(idx) == f"{r}{suit}"


def test_parse_counts_and_size():
    c = parse_hand("123m 456p 789s 11z")
    assert hand_size(c) == 11
    assert c[tile_index(1, "z")] == 2
    assert c[tile_index(2, "m")] == 1


def test_parse_is_order_and_space_insensitive():
    assert parse_hand("123m456p") == parse_hand("6p5p4p 1m 2m 3m")


def test_format_roundtrip():
    spec = "123m 456p 99s 11z"
    assert format_hand(parse_hand(spec)) == spec.replace(" ", " ")
    # canonical grouping/sorting within a suit
    assert format_hand(parse_hand("321m")) == "123m"


def test_parse_rejects_fifth_copy_and_garbage():
    with pytest.raises(ValueError):
        parse_hand("11111m")
    with pytest.raises(ValueError):
        parse_hand("8z")          # only 7 honors
    with pytest.raises(ValueError):
        parse_hand("12x")
    with pytest.raises(ValueError):
        parse_hand("123")         # no suit


def test_terminal_or_honor():
    assert is_terminal_or_honor(tile_index(1, "m"))
    assert is_terminal_or_honor(tile_index(9, "s"))
    assert is_terminal_or_honor(tile_index(5, "z"))   # White dragon
    assert not is_terminal_or_honor(tile_index(5, "m"))
