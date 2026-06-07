"""Shogi state model — a thin facade over ``python-shogi``.

The rest of the app talks to :class:`ShogiState` (SFEN, USI moves, check/mate),
not to ``python-shogi`` directly, so the rules-layer dependency stays swappable.

Notation:

- **SFEN** — the standard one-line position string. The opening position is
  ``lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1``. Uppercase
  = Black/sente (moves up the board), lowercase = White/gote. The trailing field
  is the side to move (``b``/``w``) then pieces in hand then move number.
- **USI moves** — ``7g7f`` (from-square to-square), ``7g7f+`` (promote), and drops
  ``G*5b`` (drop a Gold on 5b). Squares are file(1-9)+rank(a-i).
"""
from __future__ import annotations

import shogi

START_SFEN = shogi.Board().sfen()


class ShogiState:
    """A shogi position. Wraps a ``shogi.Board``; ``raw`` exposes it for the
    mate solver's hot push/pop loop."""

    def __init__(self, sfen: str | None = None):
        self.raw = shogi.Board(sfen) if sfen else shogi.Board()

    # ---- queries -------------------------------------------------------------
    @property
    def sfen(self) -> str:
        return self.raw.sfen()

    @property
    def black_to_move(self) -> bool:
        return self.raw.turn == shogi.BLACK

    def legal_moves(self) -> list[str]:
        return [m.usi() for m in self.raw.legal_moves]

    def is_check(self) -> bool:
        return self.raw.is_check()

    def is_checkmate(self) -> bool:
        return self.raw.is_checkmate()

    def is_game_over(self) -> bool:
        return self.raw.is_game_over()

    # ---- mutation ------------------------------------------------------------
    def push_usi(self, usi: str) -> "ShogiState":
        """Apply a USI move. Raises ``ValueError`` on an illegal/garbled move."""
        try:
            move = shogi.Move.from_usi(usi)
        except Exception as e:  # python-shogi raises a bare ValueError-ish
            raise ValueError(f"bad USI move {usi!r}: {e}") from e
        if move not in self.raw.legal_moves:
            raise ValueError(f"illegal move {usi!r} in this position")
        self.raw.push(move)
        return self

    def copy(self) -> "ShogiState":
        return ShogiState(self.sfen)

    # ---- display -------------------------------------------------------------
    def render(self) -> str:
        side = "Black (sente)" if self.black_to_move else "White (gote)"
        status = []
        if self.is_checkmate():
            status.append("CHECKMATE")
        elif self.is_check():
            status.append("check")
        head = f"{side} to move" + (f"  [{', '.join(status)}]" if status else "")
        return f"{self.raw}\n{head}"
