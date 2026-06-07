"""Tile primitives for Japanese Riichi Mahjong.

A hand is modelled as a **34-length count array** (``list[int]``) — one slot per
distinct tile kind, value = how many copies are held (0..4). This is the shape
every shanten/ukeire loop wants, so it stays the canonical form; strings are only
for I/O.

Index layout (the standard order)::

    0..8    1m..9m   man / characters   (萬)
    9..17   1p..9p   pin / circles      (筒)
    18..26  1s..9s   sou / bamboo       (索)
    27..33  honors   E S W N  White Green Red

Honors carry no suit-run, so 27..33 never form sequences.

Notation (the usual riichi shorthand) groups digits by suit letter:

    "123m 456p 789s 11z"     -> two of East as the pair
    "19m19p19s1234567z"      -> the thirteen-orphans tiles, compact

Honor digits in the ``z`` block: 1=East 2=South 3=West 4=North 5=White(haku)
6=Green(hatsu) 7=Red(chun).
"""
from __future__ import annotations

SUITS = "mpsz"  # man, pin, sou, honors
N_TILES = 34

# Pretty names for the honor tiles (z1..z7).
HONOR_NAMES = ["East", "South", "West", "North", "White", "Green", "Red"]

# The terminals + honors (used by tanyao checks and kokushi).
TERMINALS = [0, 8, 9, 17, 18, 26]            # 1m 9m 1p 9p 1s 9s
HONORS = list(range(27, 34))                  # the 7 honor tiles
TERMINALS_HONORS = TERMINALS + HONORS         # the 13 "yaochuu" kinds


def suit_base(suit: str) -> int:
    """First index of a suit block: m->0, p->9, s->18, z->27."""
    return SUITS.index(suit) * 9


def tile_index(rank: int, suit: str) -> int:
    """``(7, 's')`` -> 24. ``rank`` is 1-based; honors use 1..7."""
    if suit not in SUITS:
        raise ValueError(f"bad suit {suit!r}")
    lo, hi = (1, 7) if suit == "z" else (1, 9)
    if not lo <= rank <= hi:
        raise ValueError(f"bad rank {rank} for suit {suit!r}")
    return suit_base(suit) + (rank - 1)


def tile_name(idx: int) -> str:
    """Index -> shorthand: 24 -> '7s', 27 -> '1z' (East)."""
    if not 0 <= idx < N_TILES:
        raise ValueError(f"tile index {idx} out of range")
    suit = SUITS[idx // 9]
    return f"{idx % 9 + 1}{suit}"


def is_honor(idx: int) -> bool:
    return idx >= 27


def is_terminal_or_honor(idx: int) -> bool:
    return idx in TERMINALS_HONORS


def parse_hand(spec) -> list[int]:
    """Parse riichi notation (or an iterable of indices) to a 34-count array.

    Accepts ``"123m45p"``, with or without spaces, in any suit order. Raises on a
    5th copy of a tile (illegal) so typos surface early.
    """
    counts = [0] * N_TILES
    if not isinstance(spec, str):
        for idx in spec:
            counts[idx] += 1
    else:
        digits: list[int] = []
        for ch in spec:
            if ch.isspace():
                continue
            if ch.isdigit():
                digits.append(int(ch))
            elif ch in SUITS:
                if not digits:
                    raise ValueError(f"suit '{ch}' with no preceding digits in {spec!r}")
                for d in digits:
                    counts[tile_index(d, ch)] += 1
                digits = []
            else:
                raise ValueError(f"unexpected char {ch!r} in {spec!r}")
        if digits:
            raise ValueError(f"trailing digits {digits} with no suit in {spec!r}")
    for idx, n in enumerate(counts):
        if n > 4:
            raise ValueError(f"{n} copies of {tile_name(idx)} (max 4)")
    return counts


def format_hand(counts) -> str:
    """34-count array -> compact notation, grouped by suit: '123m 456p 77z'."""
    out = []
    for s, suit in enumerate(SUITS):
        digits = "".join(
            str(i + 1) * counts[s * 9 + i]
            for i in range(9 if suit != "z" else 7)
        )
        if digits:
            out.append(digits + suit)
    return " ".join(out)


def hand_size(counts) -> int:
    return sum(counts)
