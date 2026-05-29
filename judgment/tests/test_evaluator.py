from judgment_assist.cards import parse_cards
from judgment_assist.poker.evaluator import (
    evaluate7, category_name, STRAIGHT_FLUSH, FOUR_KIND, FULL_HOUSE, FLUSH,
    STRAIGHT, THREE_KIND, TWO_PAIR, ONE_PAIR, HIGH_CARD,
)


def ev(spec):
    return evaluate7(parse_cards(spec))


def test_categories():
    assert ev("As Ks Qs Js Ts 2c 3d")[0] == STRAIGHT_FLUSH
    assert ev("9h 9d 9c 9s 2h 3d 4c")[0] == FOUR_KIND
    assert ev("9h 9d 9c Ks Kd 4c 2h")[0] == FULL_HOUSE
    assert ev("Ah Kh 9h 5h 2h 3d 4c")[0] == FLUSH
    assert ev("5h 6d 7c 8s 9h 2c 2d")[0] == STRAIGHT
    assert ev("9h 9d 9c Ks Qd 4c 2h")[0] == THREE_KIND
    assert ev("9h 9d Ks Kd 4c 2h 3s")[0] == TWO_PAIR
    assert ev("9h 9d Ks Qd 4c 2h 7s")[0] == ONE_PAIR
    assert ev("9h 7d Ks Qd 4c 2h Ts")[0] == HIGH_CARD


def test_wheel_straight():
    # A-2-3-4-5 is a five-high straight, not ace-high
    assert ev("Ah 2d 3c 4s 5h 9d Kc") == (STRAIGHT, 5)


def test_ordering():
    assert ev("As Ks Qs Js Ts 2c 3d") > ev("9h 9d 9c 9s 2h 3d 4c")     # SF > quads
    assert ev("9h 9d 9c Ks Kd 4c 2h") > ev("Ah Kh 9h 5h 2h 3d 4c")     # boat > flush
    assert ev("Ah Ad Kc Ks 2h 3d 4c") > ev("Ah Ad Qc Qs 2h 3d 4c")     # aces+kings > aces+queens
    # better kicker wins
    assert ev("Ah Ad Kc 9s 2h 3d 4c") > ev("Ah Ad Qc 9s 2h 3d 4c")


def test_best_five_of_seven():
    # two trips -> full house using the higher trip + lower trip as pair
    r = ev("Kh Kd Kc Qh Qd Qc 2s")
    assert r == (FULL_HOUSE, 13, 12)
    assert category_name(r) == "full house"
