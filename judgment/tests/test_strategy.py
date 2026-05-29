from judgment_assist.cards import RANK_TO_INT
from judgment_assist.blackjack.strategy import (
    recommend, hand_total, bust_probability, HIT, STAND, DOUBLE, SPLIT,
)
from judgment_assist.blackjack.engine import BlackjackAdvisor, Rules
from judgment_assist.blackjack.counting import HiLoCounter


def R(*chars):
    """Build a rank list from shorthand chars, e.g. R('A','7')."""
    return [RANK_TO_INT[c] for c in chars]


def up(ch):
    return RANK_TO_INT[ch]


def test_hand_total():
    assert hand_total(R("A", "9")) == (20, True)        # soft 20
    assert hand_total(R("A", "6", "K")) == (17, False)  # ace forced to 1
    assert hand_total(R("T", "6")) == (16, False)
    assert hand_total(R("A", "A")) == (12, True)        # one ace 11, one 1


def test_hard_totals():
    assert recommend(R("T", "6"), up("T")).action == HIT
    assert recommend(R("T", "6"), up("6")).action == STAND
    assert recommend(R("5", "6"), up("5")).action == DOUBLE   # hard 11
    assert recommend(R("9", "2"), up("T")).action == DOUBLE   # hard 11 vs 10 -> double
    assert recommend(R("9", "2"), up("A")).action == HIT      # 11 vs A -> hit (S17)
    assert recommend(R("T", "7"), up("2")).action == STAND    # hard 17


def test_soft_totals():
    assert recommend(R("A", "7"), up("9")).action == HIT      # soft 18 vs 9
    assert recommend(R("A", "7"), up("3")).action == DOUBLE   # soft 18 vs 3
    assert recommend(R("A", "7"), up("8")).action == STAND    # soft 18 vs 8
    assert recommend(R("A", "2"), up("5")).action == DOUBLE   # soft 13 vs 5


def test_soft_18_no_double_falls_to_stand():
    d = recommend(R("A", "7"), up("4"), can_double=False)
    assert d.action == STAND


def test_pairs():
    assert recommend(R("8", "8"), up("T")).action == SPLIT
    assert recommend(R("A", "A"), up("5")).action == SPLIT
    assert recommend(R("T", "T"), up("6")).action == STAND    # never split tens
    assert recommend(R("9", "9"), up("7")).action == STAND    # 9s stand vs 7
    assert recommend(R("9", "9"), up("9")).action == SPLIT
    # 5,5 is treated as hard 10, not split
    assert recommend(R("5", "5"), up("6")).action == DOUBLE


def test_count_deviation_16v10():
    assert recommend(R("T", "6"), up("T")).action == HIT             # no count -> basic
    assert recommend(R("T", "6"), up("T"), true_count=1).action == STAND


def test_six_card_charlie_hint():
    adv = BlackjackAdvisor(Rules(decks=6))
    # five cards, low total -> hitting can't bust, push for the auto-win
    d = adv.advise(R("2", "3", "2", "4", "2"), up("T"))  # total 13, five cards
    assert d.action == HIT
    assert "charlie" in d.reason.lower()


def test_charlie_not_forced_when_bust_likely():
    adv = BlackjackAdvisor(Rules(decks=6))
    # five cards totalling 18 -> almost certainly busts, don't chase charlie
    d = adv.advise(R("5", "4", "3", "4", "2"), up("6"))  # total 18
    assert d.action == STAND


def test_counter_true_count():
    c = HiLoCounter(decks=1)
    c.see_many(R("2", "3", "4", "5", "6"))   # running +5
    assert c.running == 5
    assert c.true_count > 0
