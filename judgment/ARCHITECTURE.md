# Architecture & build plan

## Pipeline

```
   ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌──────────┐
   │ capture │ → │  vision  │ → │  state   │ → │  advisor  │ → │  output  │
   │ (mss)   │   │ (cv2     │   │  (cards, │   │ (equity / │   │ (console │
   │ region  │   │  template│   │  counts) │   │  strategy)│   │ /overlay)│
   └─────────┘   │  match)  │   └──────────┘   └───────────┘   └──────────┘
                 └──────────┘
```

The **capture target is always "a rectangle of this PC's screen."** That makes
the eyes layer source-agnostic: whether Judgment is a Steam window, a PS Remote
Play window, or a capture-card preview, we grab pixels the same way. Only
*input automation* (sending button presses back to the game) is source-specific
— and that's an opt-in later phase, not required for advice.

## Why template matching (not OCR / ML)

The game renders cards from a fixed set of sprites at a fixed resolution, so the
same card is pixel-identical every time. Normalised cross-correlation
(`cv2.matchTemplate`) against a small library of reference crops is fast, needs
no training, and is near-100% reliable once calibrated. We capture the template
library once from the running game (calibration step).

## Decisions (2026-05-29)

- **Source: PC Steam, borderless/windowed.** Capture targets the game window by
  title (`capture/window.py`), so ROIs survive the window being moved.
- **Advice/overlay only** for now. Phase 4 input automation is intentionally
  deferred — a misread card should never cost chips. The overlay just *shows*
  the best move; you press the buttons.

## Build phases

- [x] **Phase 0 — repo + brains.** Card primitives, poker evaluator + equity +
  advisor, blackjack basic strategy + Hi-Lo counting + Six-Card-Charlie-aware
  engine. Unit-tested (23 tests), no game required.
- [x] **Phase 1 — capture + calibration.** `mss` region grabber, Win32 window
  finder, and a calibration CLI: `windows` / `snapshot` / interactive `mark`
  (drag boxes around the card regions) / `templates` (build the reference card
  library) / manual `crop`.
- [x] **Phase 2 — vision + manual CLI.** `cv2.matchTemplate` recogniser
  (`vision/recognizer.py`) and a manual advisor CLI (`app/cli.py`, type cards →
  advice) usable with zero calibration.
- [x] **Phase 3 — live advisor loop.** `app/live.py`: capture → recognise →
  advise → always-on-top tkinter overlay (or `--no-overlay` console). *Runs once
  calibration (templates + ROIs) is done against the live game.*
- [ ] **Phase 4 (deferred) — input automation.** Out of scope by choice; would
  add blackjack auto-play via input injection to the (PC) game window.

## Remaining to use it live

The code is done; what's left needs the game on screen (one-time, ~10 min):
1. `calibrate windows` → find Judgment's window title.
2. Build the template library into `data/templates/` (collect across a few hands):
   - blackjack: `calibrate templates --mode rank --window Judgment` → just the 13
     rank glyphs (suit-agnostic), cropped from a card corner.
   - poker: `calibrate templates --window Judgment` → all 52 full cards.
3. `calibrate mark --game blackjack --window Judgment` (box the corner ranks) and
   `--game poker` (box whole cards) → writes `config/regions.json`.
4. `uv run python -m judgment_assist.app.live blackjack` (or `poker`) → overlay shows the
   play. Blackjack hands are logged to a SQLite DB by default (`--no-db` to
   disable; analyse with `-m judgment_assist.app.sessions`).

Start with blackjack: fewer ROIs, a static turn-based screen, a deterministic
(lookup) decision, and only 13 suit-agnostic templates to collect.

## Open empirical questions (the tool will answer these)

1. **Blackjack deck count & reshuffle — RESOLVED (counting retired).** It's a
   multi-seat table: other players' and the dealer's cards sit angled/clipped at
   the edges, so the reader can't observe most of the shoe → Hi-Lo counting isn't
   usable for betting regardless of reshuffle behaviour. Counting is experimental
   and off by default (`--count`); the HUD-total advice is the product.
2. **Poker opponent count & whether opponents fold pre-showdown.** Equity is
   computed vs the *active* opponent count; we read that from the table state.
3. **Exact screen resolution / window mode** for the ROI config.

## Notes on correctness

- `blackjack/strategy.py` defaults to multi-deck, dealer **stands on soft 17**,
  double-after-split allowed. Toggle via `blackjack.engine.Rules`. A handful of
  Illustrious-18 count deviations are applied only when a true count is supplied.
- `poker/equity.py` is Monte-Carlo (seedable). ~20k iters gives ~±0.3% on a
  decision we have seconds to make. Tie pots are split correctly among the
  players that actually tie.
