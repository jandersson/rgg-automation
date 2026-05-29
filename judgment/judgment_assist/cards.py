"""Card primitives shared by the blackjack and poker engines.

A card is a plain ``(rank, suit)`` tuple of ints so the hot loop in the poker
equity sampler stays allocation-free:

    rank: 2..14   (J=11, Q=12, K=13, A=14)
    suit: 0..3    (clubs, diamonds, hearts, spades)

Human-facing parsing/formatting uses the usual shorthand: ``"As"``, ``"Td"``,
``"9c"`` (rank char + suit char, suit in ``c d h s``).
"""
from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"

RANK_TO_INT = {ch: i for i, ch in enumerate(RANKS, start=2)}  # '2'->2 ... 'A'->14
INT_TO_RANK = {v: k for k, v in RANK_TO_INT.items()}
SUIT_TO_INT = {ch: i for i, ch in enumerate(SUITS)}
INT_TO_SUIT = {v: k for k, v in SUIT_TO_INT.items()}

Card = tuple  # (rank:int, suit:int)


def parse_card(s: str) -> Card:
    s = s.strip()
    if len(s) != 2:
        raise ValueError(f"bad card {s!r}: expected e.g. 'As', 'Td', '9c'")
    r, su = s[0].upper(), s[1].lower()
    if r not in RANK_TO_INT or su not in SUIT_TO_INT:
        raise ValueError(f"bad card {s!r}")
    return (RANK_TO_INT[r], SUIT_TO_INT[su])


def parse_cards(spec) -> list:
    """Parse a space/comma separated string, or an iterable of card strings."""
    parts = spec.replace(",", " ").split() if isinstance(spec, str) else list(spec)
    return [parse_card(p) for p in parts]


def card_str(c: Card) -> str:
    return INT_TO_RANK[c[0]] + INT_TO_SUIT[c[1]]


def cards_str(cards) -> str:
    return " ".join(card_str(c) for c in cards)


FULL_DECK = [(r, s) for r in range(2, 15) for s in range(4)]
assert len(FULL_DECK) == 52
