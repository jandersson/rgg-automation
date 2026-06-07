"""Shogi brain for Judgment's Outdoor Shogi (matches) and Puzzle Shogi (tsume).

Unlike poker/blackjack/mahjong, shogi's brain is a *solved* engineering problem:
strong play means a search engine, and there's a standard (USI) with mature
open-source engines. So this track is an **engine-driver foundation** rather than
a from-scratch AI:

- ``board.py``  — state model (SFEN in/out, legal moves, check/mate) over
  ``python-shogi`` (pure-Python rules layer).
- ``mate.py``   — a pure-Python forced-mate solver. Needs **no engine binary**, so
  it covers Puzzle Shogi (mate-in-N) on its own and flags forced mates in matches.
- ``engine.py`` — a pluggable USI engine driver (for full-match positional advice)
  plus the advisor facade that prefers an exact forced mate, then falls back to
  the engine if one is configured.

The heavyweight USI *engine binary* (e.g. YaneuraOu) is intentionally optional/
deferred — see ``SHOGI.md``.
"""
