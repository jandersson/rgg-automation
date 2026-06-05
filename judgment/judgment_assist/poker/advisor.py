"""Turn equity into a betting recommendation using pot odds.

Heuristic but sound: call when equity beats the pot odds, raise when it beats
them by a comfortable margin, otherwise check/fold. Margins are tunable.
"""
from .equity import equity
from .evaluator import evaluate7, category_name


def advise(hero, board=(), opponents=1, to_call=0, pot=0, iters=20000,
           seed=None, raise_margin=0.12):
    """Recommend an action.

    Parameters mirror the table state: chips already in the ``pot``, chips it
    costs to ``to_call``. With ``to_call == 0`` we're choosing whether to bet.
    """
    eq = equity(hero, board, opponents, iters, seed)
    if len(board) >= 3:
        eq["made_hand"] = category_name(evaluate7(hero + list(board)))
    return decide(eq, to_call=to_call, pot=pot, raise_margin=raise_margin)


def decide(eq, to_call=0, pot=0, raise_margin=0.12):
    """Turn a precomputed ``equity`` dict into a betting recommendation.

    Split out from :func:`advise` so a live loop can compute the expensive
    Monte-Carlo equity once (it only depends on the cards) and refresh the cheap
    pot-odds decision every frame as ``to_call``/``pot`` change."""
    e = eq["equity"]
    out = dict(eq)

    if to_call > 0:
        pot_odds = to_call / (pot + to_call)
        out["pot_odds"] = pot_odds
        out["call_ev_chips"] = e * (pot + to_call) - to_call
        if e >= pot_odds + raise_margin:
            action = "raise"
        elif e >= pot_odds:
            action = "call"
        else:
            action = "fold"
    else:
        out["pot_odds"] = 0.0
        if e > 0.62:
            action = "bet/raise"
        elif e > 0.45:
            action = "check"
        else:
            action = "check/fold"

    out["recommendation"] = action
    return out
