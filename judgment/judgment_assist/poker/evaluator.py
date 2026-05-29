"""7-card hand evaluator.

``evaluate7(cards)`` returns a tuple where a *larger* tuple is the stronger
hand. The leading element is the category, so tuples compare correctly both
within a category (equal length, kicker-by-kicker) and across categories (the
category element differs first).
"""
from collections import Counter

STRAIGHT_FLUSH = 8
FOUR_KIND = 7
FULL_HOUSE = 6
FLUSH = 5
STRAIGHT = 4
THREE_KIND = 3
TWO_PAIR = 2
ONE_PAIR = 1
HIGH_CARD = 0

CATEGORY_NAMES = {
    8: "straight flush", 7: "four of a kind", 6: "full house", 5: "flush",
    4: "straight", 3: "three of a kind", 2: "two pair", 1: "pair", 0: "high card",
}


def _straight_high(ranks):
    """Highest card of the best straight in ``ranks`` (0 if none). Ace plays
    high or low (the wheel A-2-3-4-5)."""
    rs = set(ranks)
    if 14 in rs:
        rs.add(1)  # ace can complete the wheel
    for high in range(14, 4, -1):
        if all((high - k) in rs for k in range(5)):
            return high
    return 0


def evaluate7(cards):
    ranks = [c[0] for c in cards]
    rank_counts = Counter(ranks)
    suit_counts = Counter(c[1] for c in cards)

    flush_suit = next((s for s, n in suit_counts.items() if n >= 5), None)
    if flush_suit is not None:
        sf = _straight_high([c[0] for c in cards if c[1] == flush_suit])
        if sf:
            return (STRAIGHT_FLUSH, sf)

    # ranks grouped by (count desc, rank desc)
    by_count = sorted(rank_counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    r0, n0 = by_count[0]
    r1, n1 = by_count[1] if len(by_count) > 1 else (0, 0)

    if n0 == 4:
        kicker = max(r for r in ranks if r != r0)
        return (FOUR_KIND, r0, kicker)
    if n0 == 3 and n1 >= 2:
        return (FULL_HOUSE, r0, r1)
    if flush_suit is not None:
        top = sorted((c[0] for c in cards if c[1] == flush_suit), reverse=True)[:5]
        return (FLUSH, *top)
    st = _straight_high(ranks)
    if st:
        return (STRAIGHT, st)
    if n0 == 3:
        kick = sorted((r for r in ranks if r != r0), reverse=True)[:2]
        return (THREE_KIND, r0, *kick)
    if n0 == 2 and n1 == 2:
        pairs = sorted((r for r, n in rank_counts.items() if n == 2), reverse=True)
        kicker = max(r for r in ranks if r not in pairs[:2])
        return (TWO_PAIR, pairs[0], pairs[1], kicker)
    if n0 == 2:
        kick = sorted((r for r in ranks if r != r0), reverse=True)[:3]
        return (ONE_PAIR, r0, *kick)
    return (HIGH_CARD, *sorted(ranks, reverse=True)[:5])


def category_name(rank_tuple):
    return CATEGORY_NAMES[rank_tuple[0]]
