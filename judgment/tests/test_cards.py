from judgment_assist.cards import (
    parse_card, parse_cards, card_str, cards_str, FULL_DECK,
)


def test_round_trip():
    for spec in ["As", "Td", "9c", "2h", "Kd"]:
        assert card_str(parse_card(spec)) == spec


def test_parse_cards_str_and_iter():
    a = parse_cards("As Kd 9c")
    b = parse_cards("As,Kd,9c")
    c = parse_cards(["As", "Kd", "9c"])
    assert a == b == c
    assert cards_str(a) == "As Kd 9c"


def test_full_deck_unique():
    assert len(FULL_DECK) == 52
    assert len(set(FULL_DECK)) == 52


def test_bad_card():
    for bad in ["", "A", "Xx", "1s", "Az"]:
        try:
            parse_card(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")
