"""Multi-deck blackjack basic strategy.

Defaults: 4-8 decks, dealer **stands on soft 17 (S17)**, double allowed on any
two cards, double-after-split allowed. Set ``hit_soft_17=True`` for H17 tables.
A small set of Illustrious-18 count deviations is applied only when a
``true_count`` is supplied.

``recommend(...)`` returns a ``Decision(action, reason)`` where ``action`` is
one of ``hit / stand / double / split / surrender``. Doubles only come back when
the hand is two cards and ``can_double`` is set; otherwise the correct
no-double fallback (hit or stand) is returned instead.
"""
from dataclasses import dataclass

HIT, STAND, DOUBLE, SPLIT, SURRENDER = "hit", "stand", "double", "split", "surrender"


@dataclass
class Decision:
    action: str
    reason: str = ""


def card_value(rank):
    """Blackjack value of a rank int. Ace = 11 here (the totaller demotes it)."""
    if rank == 14:
        return 11
    if rank >= 11:  # J, Q, K
        return 10
    return rank


def hand_total(ranks):
    """Return ``(total, soft)``. ``soft`` is True when an ace is still counted
    as 11 (i.e. the hand can't bust on the next card)."""
    total = sum(card_value(r) for r in ranks)
    aces = sum(1 for r in ranks if r == 14)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, (aces > 0 and total <= 21)


def bust_probability(ranks):
    """Infinite-deck probability that one more card busts this hand. Used for
    the Six-Card-Charlie hint, where we just need to not exceed 21."""
    min_total = sum(1 if r == 14 else card_value(r) for r in ranks)  # aces as 1
    room = 21 - min_total
    # value distribution of one drawn card (ace counts as its minimum, 1):
    probs = {1: 1 / 13}                       # ace
    probs.update({v: 1 / 13 for v in range(2, 10)})
    probs[10] = 4 / 13                        # T, J, Q, K
    return sum(p for v, p in probs.items() if v > room)


def _is_pair(ranks):
    return len(ranks) == 2 and card_value(ranks[0]) == card_value(ranks[1])


def recommend(player_ranks, dealer_up, *, can_double=True, can_split=True,
              can_surrender=False, true_count=None, hit_soft_17=False):
    d = card_value(dealer_up)            # 2..11 (ace = 11)
    total, soft = hand_total(player_ranks)
    two = len(player_ranks) == 2
    tc = true_count

    def ge(threshold):  # count-deviation guard: True only when a count is given
        return tc is not None and tc >= threshold

    # ---- late surrender ----
    if can_surrender and two and not soft:
        if total == 16 and d in (9, 10, 11):
            return Decision(SURRENDER, "hard 16 vs 9/10/A")
        if total == 15 and d == 10:
            return Decision(SURRENDER, "hard 15 vs 10")

    # ---- pairs ----
    if can_split and _is_pair(player_ranks):
        pv = card_value(player_ranks[0])
        if pv == 11:
            return Decision(SPLIT, "always split aces")
        if pv == 10:
            return Decision(STAND, "never split tens")
        if pv == 9:
            if d in (2, 3, 4, 5, 6, 8, 9):
                return Decision(SPLIT, "split 9s vs 2-6, 8-9")
            return Decision(STAND, "9s stand vs 7, 10, A")
        if pv == 8:
            return Decision(SPLIT, "always split 8s")
        if pv == 7 and d <= 7:
            return Decision(SPLIT, "split 7s vs 2-7")
        if pv == 6 and d <= 6:
            return Decision(SPLIT, "split 6s vs 2-6")
        if pv == 4 and d in (5, 6):
            return Decision(SPLIT, "split 4s vs 5-6 (DAS)")
        if pv in (2, 3) and d <= 7:
            return Decision(SPLIT, "split 2s/3s vs 2-7")
        # any other pair (incl. 5s) plays as its total below

    # ---- soft totals ----
    if soft:
        if total >= 20:
            return Decision(STAND, "soft 20")
        if total == 19:
            if hit_soft_17 and d == 6 and two and can_double:
                return Decision(DOUBLE, "soft 19 double vs 6 (H17)")
            return Decision(STAND, "soft 19")
        if total == 18:
            if d in (3, 4, 5, 6) and two and can_double:
                return Decision(DOUBLE, "soft 18 double vs 3-6")
            if d in (2, 3, 4, 5, 6, 7, 8):
                return Decision(STAND, "soft 18 stand vs 2-8")
            return Decision(HIT, "soft 18 hit vs 9/10/A")
        if total == 17:
            if d in (3, 4, 5, 6) and two and can_double:
                return Decision(DOUBLE, "soft 17 double vs 3-6")
            return Decision(HIT, "soft 17 hit")
        if total in (15, 16):
            if d in (4, 5, 6) and two and can_double:
                return Decision(DOUBLE, f"soft {total} double vs 4-6")
            return Decision(HIT, f"soft {total} hit")
        if total in (13, 14):
            if d in (5, 6) and two and can_double:
                return Decision(DOUBLE, f"soft {total} double vs 5-6")
            return Decision(HIT, f"soft {total} hit")
        return Decision(HIT, "soft low hit")

    # ---- hard totals ----
    if total >= 17:
        return Decision(STAND, f"hard {total}")
    if total == 16:
        if d == 10 and ge(0):
            return Decision(STAND, "16 vs 10 stand (TC>=0)")
        if d == 9 and ge(5):
            return Decision(STAND, "16 vs 9 stand (TC>=5)")
        return Decision(STAND, "16 stand vs 2-6") if d <= 6 else Decision(HIT, "16 hit vs 7+")
    if total == 15:
        if d == 10 and ge(4):
            return Decision(STAND, "15 vs 10 stand (TC>=4)")
        return Decision(STAND, "15 stand vs 2-6") if d <= 6 else Decision(HIT, "15 hit vs 7+")
    if total in (13, 14):
        return Decision(STAND, f"{total} stand vs 2-6") if d <= 6 else Decision(HIT, f"{total} hit vs 7+")
    if total == 12:
        if d == 2 and ge(3):
            return Decision(STAND, "12 vs 2 stand (TC>=3)")
        if d == 3 and ge(2):
            return Decision(STAND, "12 vs 3 stand (TC>=2)")
        return Decision(STAND, "12 stand vs 4-6") if d in (4, 5, 6) else Decision(HIT, "12 hit")
    if total == 11:
        if two and can_double:
            if d == 11 and not (hit_soft_17 or ge(1)):
                return Decision(HIT, "11 vs A hit (S17)")
            return Decision(DOUBLE, "11 double")
        return Decision(HIT, "11 hit")
    if total == 10:
        if two and can_double and 2 <= d <= 9:
            return Decision(DOUBLE, "10 double vs 2-9")
        return Decision(HIT, "10 hit vs 10/A")
    if total == 9:
        if two and can_double and d in (3, 4, 5, 6):
            return Decision(DOUBLE, "9 double vs 3-6")
        if two and can_double and d == 2 and ge(1):
            return Decision(DOUBLE, "9 vs 2 double (TC>=1)")
        return Decision(HIT, "9 hit")
    return Decision(HIT, f"hard {total} hit")
