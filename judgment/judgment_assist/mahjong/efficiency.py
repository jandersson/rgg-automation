"""Efficiency advisor — ukeire (tile acceptance) and the best discard.

This is the v1 brain: given the tiles you hold, which tile should you throw to
get to a win fastest? "Fastest" = minimise shanten, then maximise *ukeire* — the
number of tiles still live that would lower your shanten.

It is **pure speed/efficiency**: it does not yet weigh yaku, dora, or defence.
That's the documented next phase (see ``MAHJONG.md``). For someone learning, the
efficiency cut is the single most useful hint, and it's exact.
"""
from __future__ import annotations

from .shanten import shanten
from .tiles import N_TILES, format_hand, hand_size, tile_name

MAX_PER_TILE = 4


def ukeire(counts, seen=None):
    """Tiles that lower this hand's shanten, with how many remain live.

    ``counts`` should be a 13-tile hand (or any non-14 hand at a decision point).
    Returns ``(tiles, total)`` where ``tiles`` is a sorted list of
    ``(index, remaining)`` and ``total`` is the summed remaining count.

    ``seen`` is an optional 34-count array of tiles visible elsewhere (your own
    discards, opponents' discards, dora indicator) so the remaining count is
    honest. Tiles in your hand are always subtracted. Without it, only the hand
    is subtracted (an optimistic upper bound, fine for a first-pass advisor).
    """
    base = shanten(counts)
    c = list(counts)
    accept = []
    for t in range(N_TILES):
        used = c[t] + (seen[t] if seen else 0)
        if used >= MAX_PER_TILE:
            continue
        c[t] += 1
        if shanten(c) < base:
            accept.append((t, MAX_PER_TILE - used))
        c[t] -= 1
    total = sum(n for _, n in accept)
    return accept, total


def discard_options(counts, seen=None):
    """Rank every legal discard from a 14-tile hand.

    Returns a list of dicts sorted best-first, each::

        {tile, shanten, ukeire, accepts}

    where ``shanten`` is the resulting hand's shanten after the discard,
    ``ukeire`` the total live accepting tiles, and ``accepts`` the
    ``(index, remaining)`` breakdown. Best = lowest shanten, then highest ukeire.
    """
    if hand_size(counts) % 3 != 2:
        raise ValueError(
            f"expected a 14-tile (3n+2) hand to discard from, got {hand_size(counts)} tiles"
        )
    c = list(counts)
    out = []
    for t in range(N_TILES):
        if c[t] == 0:
            continue
        c[t] -= 1
        accepts, total = ukeire(c, seen)
        out.append(
            {
                "tile": t,
                "shanten": shanten(c),
                "ukeire": total,
                "accepts": accepts,
            }
        )
        c[t] += 1
    out.sort(key=lambda d: (d["shanten"], -d["ukeire"], d["tile"]))
    return out


def best_discard(counts, seen=None):
    """The single recommended discard (first of :func:`discard_options`)."""
    return discard_options(counts, seen)[0]


def format_options(options, limit=5) -> str:
    """Human-readable summary of the top discard options."""
    lines = []
    for d in options[:limit]:
        tiles = " ".join(f"{tile_name(t)}({n})" for t, n in d["accepts"]) or "—"
        sh = "win" if d["shanten"] < 0 else f"{d['shanten']}-shanten"
        lines.append(
            f"discard {tile_name(d['tile']):>3}  -> {sh:<10} "
            f"ukeire {d['ukeire']:>2}  [{tiles}]"
        )
    return "\n".join(lines)
