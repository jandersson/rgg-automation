# Architecture & build plan

> **Status (2026-06-06).** This doc is the original (blackjack-first, template-
> matching) build plan and is kept for the record, but the project has two tracks
> now and the poker one diverged from the assumptions below:
> - **Blackjack** — HUD-total advice (reads the dealer/player "Total" badges); the
>   reliable product. Hi-Lo counting is experimental/off (multi-seat table).
> - **Poker (Texas Hold'em)** — the +EV track, **semi-automatic** and run from a
>   GUI **launcher** (`app/launcher.py`): a display-only overlay floats over the
>   game while a **Labels** tab manages the training data. The brain (equity +
>   pot-odds) is solid; the *eyes* read the pot/bets/street reliably but card
>   **rank/suit reading does not fully work** (the documented wall) — it's an
>   advisory HOG+SVM read the human confirms/corrects. **POKER.md is canonical for
>   poker**; read it first for anything poker-related.
>
> Net correction to the section below: template matching is near-100% only for
> the *fixed HUD glyphs* (digits, the blackjack felt rank). Reading a card's
> rank+suit off the felt is the hard part and is NOT solved by template matching.

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

## Reading the screen — what works, what doesn't

The original bet was "template matching everywhere": the game renders from fixed
sprites at a fixed resolution, so normalised cross-correlation
(`cv2.matchTemplate`) against a small reference library is fast and needs no
training. That held for the **fixed HUD glyphs** — the blackjack "Total" badge
digits and the poker pot/bet plates (white digits, `vision/hud.py`) — which read
reliably once calibrated.

It did **not** hold for reading a card's **rank+suit off the felt**. We tried
template matching, raw-pixel/HOG SVMs, a CNN, and temporal voting (263 frames,
~100 labeled cards); whole-card HOG+SVM topped out and the errors are *systematic*
(lookalikes: 9↔T, J↔K), not random — see POKER.md for the full record. So:

- **Blackjack** advises off the HUD totals (reliable), optionally upgraded by the
  felt rank templates when they read.
- **Poker** uses a whole-card **HOG + LinearSVC** reader (`vision/poker_cards.py`)
  as an **advisory** hole/board guess (~90% rank on the current library, lower on
  a fresh table), and the hero confirms/corrects via the launcher. The reader
  refits as you correct, and the **Labels** tab curates that training set. Colour
  (red/black) is the one near-100% card signal and gates the suit choice.

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
- [x] **Phase 3.5 — poker semi-auto + launcher.** `app/launcher.py` is the poker
  app: runs the advisor in-process, floats a display-only overlay over the game,
  and hosts the **Corrections** panel (fix a mis-read hole/board card) and the
  **Labels** tab (review/curate the HOG+SVM training library — fix/skip/delete,
  capture from the game, import frames, reviewed-tracking). A global confirm key
  (e.g. a controller back-paddle → Insert) confirms a hand in play and marks
  crops reviewed on the Labels tab. Blackjack still runs as a subprocess.
- [ ] **Phase 4 (deferred) — input automation.** Out of scope by choice; advice
  only — a misread card should never cost chips.

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

Blackjack is the simplest to stand up (fewer ROIs, a static turn-based screen, a
lookup decision, 13 suit-agnostic templates). **Poker** is the day-to-day tool:
launch it with `app/launcher.py` (no console needed) — it auto-reads pot / street
/ opponents / to-call and auto-detects your hole+board as an advisory guess you
confirm or correct; equity + pot-odds give the call. See **POKER.md** for the
poker reader, the correction/learning loop, and the Labels tab.

## Open empirical questions (the tool will answer these)

1. **Blackjack deck count & reshuffle — RESOLVED (counting retired).** It's a
   multi-seat table: other players' and the dealer's cards sit angled/clipped at
   the edges, so the reader can't observe most of the shoe → Hi-Lo counting isn't
   usable for betting regardless of reshuffle behaviour. Counting is experimental
   and off by default (`--count`); the HUD-total advice is the product.
2. **Poker opponent count & folds — RESOLVED.** Equity is computed vs the *active*
   opponent count, read from the table state: each seat's "Fold" banner carries a
   distinctive cyan double-chevron icon, so a saturated-cyan pixel count separates
   folded from active cleanly (`vision/poker.py`). A folded seat is dropped from
   the active count and never sets the to-call price.
3. **Exact screen resolution / window mode** for the ROI config. (ROIs in
   `config/regions.json` are calibrated against Judgment's window client area.)

## Notes on correctness

- `blackjack/strategy.py` defaults to multi-deck, dealer **stands on soft 17**,
  double-after-split allowed. Toggle via `blackjack.engine.Rules`. A handful of
  Illustrious-18 count deviations are applied only when a true count is supplied.
- `poker/equity.py` is Monte-Carlo (seedable). ~20k iters gives ~±0.3% on a
  decision we have seconds to make. Tie pots are split correctly among the
  players that actually tie.
