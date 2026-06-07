"""Forced-mate (tsume) solver — pure Python, no engine binary required.

Given a position with the **attacker to move**, search for a sequence that forces
checkmate within ``max_moves`` *attacker* moves (the way tsume puzzles are
counted: mate-in-1, -3, -5 ...). Returns the principal variation as USI strings
(attacker and defender moves interleaved) or ``None`` if no forced mate exists.

``require_check=True`` (the default) restricts the attacker to *checking* moves —
the strict tsume rule, and what Judgment's Puzzle Shogi wants. Set it ``False`` to
look for any forced mate in a live match (slower; the defender must still answer
every line). The search is exhaustive over legal moves, so it's exact but
exponential — fine for the short mates these puzzles use, not for deep ones.
"""
from __future__ import annotations

import shogi


def find_mate(board: shogi.Board, max_moves: int, require_check: bool = True):
    """Return the PV (list of USI moves) of a forced mate, or ``None``.

    ``board`` is mutated during search but restored on return. ``max_moves`` is the
    number of attacker moves allowed (use 1 for mate-in-1, 3 for mate-in-3, ...).
    """
    if max_moves < 1:
        raise ValueError("max_moves must be >= 1")
    return _attack(board, max_moves, require_check)


def _attack(board, n, require_check):
    """Attacker to move with ``n`` attacker-moves left. Returns a PV or None."""
    for m in list(board.legal_moves):
        board.push(m)
        try:
            if require_check and not board.is_check():
                continue
            if board.is_checkmate():
                return [m.usi()]
            if n == 1:
                continue  # out of attacker moves and not yet mate
            pv = _defend(board, n - 1, require_check)
            if pv is not None:
                return [m.usi()] + pv
        finally:
            board.pop()
    return None


def _defend(board, n, require_check):
    """Defender to move. Mate is forced only if *every* reply still loses; returns
    the line after the defender's most stubborn (longest) defence, else None."""
    moves = list(board.legal_moves)
    if not moves:
        # Defender has no move. In shogi there's no stalemate-as-draw, and a true
        # mate was already detected by the attacker, so reaching here means the
        # position isn't a mate we can claim.
        return None
    longest = []
    for d in moves:
        board.push(d)
        try:
            sub = _attack(board, n, require_check)
        finally:
            board.pop()
        if sub is None:
            return None  # this defence escapes -> not forced
        if 1 + len(sub) > len(longest):
            longest = [d.usi()] + sub
    return longest


def mate_in(pv) -> int:
    """Attacker-move count of a PV from :func:`find_mate` (mate-in-N)."""
    return (len(pv) + 1) // 2
