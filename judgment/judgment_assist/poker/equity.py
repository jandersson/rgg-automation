"""Monte-Carlo Texas Hold'em equity vs. N random opponents.

Seedable so results are reproducible in tests. We have seconds to make each
in-game decision, so ~20k iterations (≈±0.3%) is plenty.
"""
import random

from ..cards import FULL_DECK
from .evaluator import evaluate7


def equity(hero, board=(), opponents=1, iters=20000, seed=None):
    """Win/tie/lose probabilities for ``hero`` (2 hole cards) against
    ``opponents`` random hands given the current ``board`` (0-5 community cards).

    ``equity`` in the result is the share of the pot hero wins on average:
    a win counts 1, a tie counts 1/(players sharing).
    """
    rng = random.Random(seed)
    hero = list(hero)
    board = list(board)
    known = set(hero) | set(board)
    deck = [c for c in FULL_DECK if c not in known]
    need = 5 - len(board)
    draw = need + 2 * opponents

    wins = ties = 0
    eq_sum = 0.0
    for _ in range(iters):
        sample = rng.sample(deck, draw)
        community = board + sample[:need]
        hero_rank = evaluate7(hero + community)
        idx = need
        opp_ranks = []
        for _o in range(opponents):
            opp_ranks.append(evaluate7(sample[idx:idx + 2] + community))
            idx += 2
        best_opp = max(opp_ranks)
        if hero_rank > best_opp:
            wins += 1
            eq_sum += 1.0
        elif hero_rank == best_opp:
            ties += 1
            tied = sum(1 for r in opp_ranks if r == best_opp)
            eq_sum += 1.0 / (1 + tied)
        # else: loss, contributes 0

    n = float(iters)
    return {
        "win": wins / n,
        "tie": ties / n,
        "lose": (iters - wins - ties) / n,
        "equity": eq_sum / n,
        "iters": iters,
        "opponents": opponents,
    }
