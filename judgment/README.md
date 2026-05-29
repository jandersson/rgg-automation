# Judgment minigame assistant

Real-time move advisor for Judgment's casino minigames. Two layers:

1. **Brains** (`judgment_assist/poker`, `judgment_assist/blackjack`) — pure
   Python game theory. No game or screen needed; fully unit-tested. Usable
   *today* via the manual CLI: read your cards off the screen, type them, get
   the optimal play.
2. **Eyes** (`judgment_assist/capture`, `judgment_assist/vision`) — grab a
   region of the screen and recognise the cards automatically, so the advice
   appears without typing. Needs one-time calibration against the actual game.

## What the games actually are (verified)

**Poker = Texas Hold'em.** You get 2 hole cards; 5 community cards arrive as
flop/turn/river with a betting round each; best 5-of-7 wins. There are several
opponents at the table. So the right question is *"what's my equity vs N
opponents given the board?"* plus pot odds — not a draw-discard calc.

**Blackjack** — standard 21 with these house rules:
- Blackjack pays **2.5×** the bet (i.e. 3:2).
- **Six-Card Charlie**: hold 6 cards without busting → automatic win. This is a
  real strategy lever (it pays to keep hitting a stiff hand once you're at 5).
- Insurance offered on dealer Ace; push returns the bet.
- **Unknown / to be measured:** number of decks and whether the shoe is
  reshuffled every hand. *Card counting only helps if the game keeps a
  persistent shoe.* The tool tracks cards seen across hands so we can detect
  reshuffles and confirm whether counting is worth anything here.

## Quick start (brains only — works now)

```powershell
cd C:\Users\jonaS\dev\jonas\rgg-automation\judgment
py -m pip install -r requirements.txt        # for tests you only need pytest
py -m pytest                                  # run the logic tests
```

Manual advisor CLI (poker / blackjack) lands with the capture layer — see
[ARCHITECTURE.md](ARCHITECTURE.md) for the build phases.

## Layout

```
judgment_assist/
  cards.py            card primitives + parsing ("As", "Td", "9c")
  poker/
    evaluator.py      7-card hand evaluator
    equity.py         Monte-Carlo equity vs N opponents
    advisor.py        equity + pot odds -> recommendation
  blackjack/
    strategy.py       multi-deck basic strategy (+ count deviations)
    counting.py       Hi-Lo running/true count + bet ramp
    engine.py         advisor tying strategy + counting + Six-Card Charlie
  capture/            screen-region grab (mss) + calibration tool   [phase 2]
  vision/             card recognition via template matching         [phase 2]
  app/                live advisor loops + manual CLI                [phase 2]
tests/                pytest suite for the brains
config/               regions.example.json -> copy to regions.json after calibration
```
