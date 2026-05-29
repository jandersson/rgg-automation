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

## Build phases

- [x] **Phase 0 — repo + brains.** Card primitives, poker evaluator + equity +
  advisor, blackjack basic strategy + Hi-Lo counting + Six-Card-Charlie-aware
  engine. Unit-tested, no game required.
- [ ] **Phase 1 — capture + calibration.** `mss` region grabber; a calibration
  CLI that screenshots the game, lets you mark the card regions (ROIs) for each
  minigame, and crops the reference template library.
- [ ] **Phase 2 — vision + manual CLI.** `cv2.matchTemplate` recogniser wired to
  the ROIs; a manual CLI (type your cards, get advice) usable before vision is
  calibrated.
- [ ] **Phase 3 — live advisor loop.** Capture → recognise → advise → on-screen
  overlay (transparent always-on-top window) or console, updating per frame.
- [ ] **Phase 4 (optional, PC only) — input automation.** Blackjack auto-play by
  sending inputs to the game window. Poker stays advice-only by request.

## Open empirical questions (the tool will answer these)

1. **Blackjack deck count & reshuffle.** Track every card seen; flag when a card
   already seen "this shoe" reappears (⇒ reshuffle) and estimate deck count from
   the reshuffle cadence. Decides whether Hi-Lo counting has any edge.
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
