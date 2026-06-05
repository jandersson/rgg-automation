from judgment_assist.cards import parse_cards
from judgment_assist.poker.equity import equity
from judgment_assist.poker.advisor import advise, decide


def test_pocket_aces_heads_up():
    eq = equity(parse_cards("Ah As"), opponents=1, iters=6000, seed=1)
    # AA is ~85% heads-up preflop
    assert 0.80 < eq["equity"] < 0.90


def test_seventytwo_is_weak():
    eq = equity(parse_cards("7d 2c"), opponents=1, iters=6000, seed=1)
    assert eq["equity"] < 0.40


def test_equity_drops_with_more_opponents():
    one = equity(parse_cards("Ah Ks"), opponents=1, iters=6000, seed=2)["equity"]
    five = equity(parse_cards("Ah Ks"), opponents=5, iters=6000, seed=2)["equity"]
    assert one > five


def test_made_flush_on_board_is_strong():
    eq = equity(parse_cards("Ah Kh"), board=parse_cards("Qh 7h 2h"),
                opponents=2, iters=6000, seed=3)
    assert eq["equity"] > 0.80   # nut flush already made


def test_advisor_folds_bad_pot_odds():
    out = advise(parse_cards("7d 2c"), opponents=1, to_call=80, pot=20,
                 iters=4000, seed=4)
    assert out["recommendation"] == "fold"


def test_advisor_raises_strong_hand():
    out = advise(parse_cards("Ah As"), opponents=1, to_call=10, pot=100,
                 iters=4000, seed=5)
    assert out["recommendation"] == "raise"


def test_decide_reuses_cached_equity():
    # the live loop's path: compute equity once, then re-decide as the price moves
    eq = equity(parse_cards("Ah Ks"), board=parse_cards("Ah 7c 2d"),
                opponents=1, iters=4000, seed=6)
    cheap = decide(eq, to_call=10, pot=200)        # great odds -> commit
    pricey = decide(eq, to_call=400, pot=20)        # terrible odds, same hand
    assert cheap["recommendation"] in ("call", "raise")
    assert pricey["recommendation"] == "fold"
    assert cheap["equity"] == eq["equity"]          # equity carried through, not recomputed
