"""Japanese Riichi Mahjong brain for Judgment's Mahjong / Wareme Mahjong.

Phase 0 is an *efficiency advisor*: read a hand, compute how far it is from a win
(shanten), which tiles improve it (ukeire), and which tile to discard to advance
fastest. No game capture needed — pure, unit-tested logic, mirroring how the
poker/blackjack brains were built first.

See ``MAHJONG.md`` for the rules primer and what this does / doesn't yet cover.
"""
