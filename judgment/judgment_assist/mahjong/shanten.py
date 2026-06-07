"""Shanten — how many tile swaps a hand is from *tenpai* (ready to win).

Convention used here:

    -1  complete winning hand (4 sets + a pair, or a special hand)
     0  tenpai: one useful tile away from winning
     n  n tiles away from tenpai

A legal standard hand is **four sets + one pair**. A *set* is a triplet
(three identical) or a run (three consecutive in one number suit). Honors never
run. Two special hands bypass that shape:

    chiitoitsu  seven distinct pairs
    kokushi     the thirteen terminals/honors, one of them paired

The overall shanten of a 13/14-tile hand is the min over those three forms.

Counts arrays (length 34, see :mod:`.tiles`) only — no per-tile objects in the
recursion, which keeps the ukeire sweep (34 draws × this) cheap.
"""
from __future__ import annotations

from .tiles import N_TILES, TERMINALS_HONORS


def shanten(counts) -> int:
    """Min shanten over standard / chiitoitsu / kokushi forms."""
    return min(
        standard_shanten(counts),
        chiitoitsu_shanten(counts),
        kokushi_shanten(counts),
    )


def is_complete(counts) -> bool:
    """True if the (14-tile) hand is a finished winning shape."""
    return shanten(counts) == -1


# ------------------------------------------------------------- standard form ---
def standard_shanten(counts) -> int:
    """Shanten toward 4 sets + 1 pair.

    Enumerate every possible head pair (plus the headless case), then for each,
    find the decomposition of the rest that maximises ``2*melds + partials`` with
    at most four blocks. ``shanten = 8 - 2*melds - partials [- 1 if head]``.
    """
    c = list(counts)
    best = 8 - _max_blocks(c, 0, 0, 0)  # headless: a pair still owed
    for t in range(N_TILES):
        if c[t] >= 2:
            c[t] -= 2
            best = min(best, 8 - _max_blocks(c, 0, 0, 0) - 1)
            c[t] += 2
    return best


def _max_blocks(c, i, melds, partials) -> int:
    """Max of ``2*melds + partials`` reachable, capped at 4 blocks total.

    A *meld* is a finished triplet/run (worth 2); a *partial* is a pair or a
    two-tile proto-run needing one tile (worth 1). DFS from the lowest tile still
    present, trying every interpretation, so it isn't fooled by greedy choices.
    """
    if melds + partials == 4:
        return 2 * melds + partials
    while i < N_TILES and c[i] == 0:
        i += 1
    if i == N_TILES:
        return 2 * melds + partials

    best = 0
    is_num = i < 27
    seq_ok = is_num and i % 9 <= 6  # a run i,i+1,i+2 stays inside one suit

    if c[i] >= 3:  # triplet
        c[i] -= 3
        best = max(best, _max_blocks(c, i, melds + 1, partials))
        c[i] += 3
    if seq_ok and c[i + 1] and c[i + 2]:  # run
        c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
        best = max(best, _max_blocks(c, i, melds + 1, partials))
        c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
    if c[i] >= 2:  # pair (partial toward a triplet, or a head candidate)
        c[i] -= 2
        best = max(best, _max_blocks(c, i, melds, partials + 1))
        c[i] += 2
    if is_num and i % 9 <= 7 and c[i + 1]:  # ryanmen/penchan i,i+1
        c[i] -= 1; c[i + 1] -= 1
        best = max(best, _max_blocks(c, i, melds, partials + 1))
        c[i] += 1; c[i + 1] += 1
    if seq_ok and c[i + 2]:  # kanchan i,_,i+2
        c[i] -= 1; c[i + 2] -= 1
        best = max(best, _max_blocks(c, i, melds, partials + 1))
        c[i] += 1; c[i + 2] += 1

    c[i] -= 1  # leave this tile floating
    best = max(best, _max_blocks(c, i, melds, partials))
    c[i] += 1
    return best


# --------------------------------------------------------- chiitoitsu (7 pr) ---
def chiitoitsu_shanten(counts) -> int:
    """Seven distinct pairs. Needs 7 *different* kinds — duplicates don't help."""
    pairs = sum(1 for n in counts if n >= 2)
    kinds = sum(1 for n in counts if n >= 1)
    return 6 - pairs + max(0, 7 - kinds)


# ------------------------------------------------------ kokushi (13 orphans) ---
def kokushi_shanten(counts) -> int:
    """Thirteen terminals/honors, one paired."""
    kinds = sum(1 for t in TERMINALS_HONORS if counts[t] >= 1)
    has_pair = any(counts[t] >= 2 for t in TERMINALS_HONORS)
    return 13 - kinds - (1 if has_pair else 0)
