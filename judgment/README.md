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

## Setup (uv)

This project uses [uv](https://docs.astral.sh/uv/). One command creates the
virtualenv (`.venv`), installs deps pinned by `uv.lock`, and installs the
package editable:

```powershell
cd C:\Users\jonaS\dev\jonas\rgg-automation\judgment
uv sync                                        # create .venv + install
uv run pytest                                  # run the logic tests
```

`uv run <cmd>` runs inside the managed env — no `pip install`, no `PYTHONPATH`.

## Manual advisor (works now — no capture)

```powershell
# blackjack: your hand vs dealer up-card (--seen feeds the count)
uv run python -m judgment_assist.app.cli blackjack --hand "T 6" --dealer T

# poker (Hold'em): hole cards, board, opponents, pot, cost-to-call
uv run python -m judgment_assist.app.cli poker --hole "Ah Kh" --board "Qh 7h 2h" --opp 2
```

Both also run as interactive REPLs (omit `--hand` / `--hole`).

## Live overlay (needs one-time calibration vs the running game)

Source is **PC Steam, borderless/windowed**; advice/overlay only (no inputs are
sent to the game). With Judgment open on the blackjack/poker table:

```powershell
uv run python -m judgment_assist.capture.calibrate windows                          # find the title
# blackjack needs only the 13 rank glyphs (suit-agnostic):
uv run python -m judgment_assist.capture.calibrate templates --mode rank --window Judgment
uv run python -m judgment_assist.capture.calibrate mark --game blackjack --window Judgment
uv run python -m judgment_assist.app.live blackjack                                 # overlay shows the play
```

You can also mark HUD/card ROIs on a saved Steam **F12** screenshot with
`--image captures\shot.jpg` (avoids the game's pause-on-focus-loss).

Poker uses full cards (suits matter for flushes), so build its library with the
default card mode: `calibrate templates --window Judgment` (all 52) and
`calibrate mark --game poker --window Judgment`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full calibration walkthrough and
the build-phase status.

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
