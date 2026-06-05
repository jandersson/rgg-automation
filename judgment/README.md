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

> **Poker status:** the equity/pot-odds *brain* works (manual CLI below), and the
> chip/pot OCR + street/suit reading are reliable, but **fully-automatic card
> reading is not achievable on this game** (cards overlap, banners cover them, and
> there's no HUD total to cross-check; ~80% rank ceiling vs the ~97%/card a 7-card
> hand needs). The realistic tool is **semi-automatic**: type your cards, it reads
> the pot/odds. Full write-up in [POKER.md](POKER.md).

**Blackjack** — standard 21 with these house rules:
- Dealer **stands on 17 (S17)**; **late surrender** offered; blackjack pays **3:2**.
- **Six-Card Charlie**: hold 6 cards without busting → automatic win. A real
  strategy lever (it pays to keep hitting a stiff hand once you're at 5).
- **Split** offered on a pair; insurance on dealer Ace; push returns the bet.
- **Multi-seat table → counting retired.** Other players and the dealer are dealt
  from the same shoe, but their cards sit angled/clipped at the screen edges, so
  the reader can't see most of the shoe and Hi-Lo counting isn't usable for
  betting (and the shoe may reshuffle each hand anyway — unconfirmed). Counting is
  therefore **experimental and off by default** (`--count`). The reliable product
  is the **HUD-total move advice**, which is unaffected.

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

**Poker is semi-automatic.** The overlay auto-reads everything it can — pot,
street, active-opponent count, cost-to-call — and **auto-detects your hole
cards**, which you confirm or correct by typing. Card reading off the screen is a
documented ~80% wall (see [POKER.md](POKER.md)), so a detected hand is a *guess*:
suit colour is reliable, rank/exact-suit are not. A typed hand locks until the
next deal (the hole slots emptying re-arms detection):

```powershell
uv run python -m judgment_assist.app.live poker
#   it shows e.g.  YOU 9c 8h  (detected black/red - type to fix)
#   Ah Kh  confirm/fix hole   | Qh 7h 2h  board   + Td  deal   c  clear   q  quit
```

It needs the `poker` ROIs, the white-on-plate digit glyphs (`--poker-digits`,
default `data/poker_digits`), and the labeled corner crops used for detection
(`--poker-cards`, default `data/poker_cards`; pass `--no-detect` to type every
card). The opponent Bet plates and fold banners are read label-free (folds
spotted by the cyan banner icon).

The card reader matches rank glyphs at multiple scales (cards render smaller in
some cascade positions) with per-rank score floors for the court letters (Q/J
false-match grey card decoration). It reads the player's own hand to upgrade the
advice to double/split/soft; if a card is misread it falls back to correct
totals-only advice, so a bad read never gives wrong advice.

## Session logging & tooling

The live blackjack advisor logs every finished hand to a SQLite DB **by default**
(`data/sessions/sessions.db`; pass `--no-db` to turn it off). It records the
reliable signals — outcome, your total, the dealer up-card — one row per hand.
Review outcomes, win/loss streaks, and a fair-deck dealer-distribution check with:

```powershell
uv run python -m judgment_assist.app.sessions data/sessions/sessions.db
```

To improve the card reader, label crops with the reusable GUI — it presents
images, you tag rank+colour (predictions pre-filled), and the labels feed
template/threshold fixes:

```powershell
uv run python -m judgment_assist.app.label --cards data/screens/frame_004*.png
```

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
    counting.py       Hi-Lo counter (experimental — see the multi-seat note above)
    engine.py         advisor tying strategy + counting + Six-Card Charlie
  vision/
    locate/recognizer  card localize + multi-scale rank match (blackjack)
    hud.py             HUD digit reader (badge Otsu + poker white-on-plate mode)
    poker.py           label-free poker state (street, opp bets/folds, to_call)
    poker_cards.py     advisory hole-card detection (colour + exemplar match)
  capture/            screen-region grab (mss) + calibration + crop harvesting
  labeling.py         reusable image-labeling core (LabelSession)
  sessions.py         SQLite session/hand telemetry + summary
  app/                cli.py (manual), live.py (overlay), label.py (labeler GUI),
                      sessions.py (report), verify_gui.py
tests/                pytest suite (brains + vision + tooling)
config/               regions.example.json -> copy to regions.json after calibration
```

See [POKER.md](POKER.md) for the poker status/findings and [ARCHITECTURE.md](ARCHITECTURE.md)
for the build plan.
