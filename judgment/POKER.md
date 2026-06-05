# Poker (Texas Hold'em) — status & findings

Honest record of the poker track as of 2026-06-05. **Bottom line: the poker *brain*
works and several *eyes* are reliable, but fully-automatic card reading is not
achievable on this game — the realistic tool is semi-automatic (you type the cards,
it reads the pot/odds).**

## The brain — works today

`poker/evaluator.py` (7-card eval), `equity.py` (Monte-Carlo equity vs N opponents),
`advisor.py` (equity + pot odds → fold/call/raise). Pure Python, tested, usable now
via the manual CLI:

```
uv run python -m judgment_assist.app.cli poker --hole "Ah Kh" --board "Qh 7h 2h" --opp 2
```

## The eyes

| Piece | Status | Notes |
|---|---|---|
| **Chip / pot OCR** | ✅ reliable | `HudReader.read(white=True)` — see below. Pot 0/20/80 read at 0.82–0.94. |
| **Street detection** | ✅ reliable | `vision/poker.py` `street()` — counts board cards (preflop/flop/turn/river). Label-free. |
| **Suit recognition** | ~90% | colour red/black = 100% (ink-pixel redness); within-colour shape ~good. |
| **Card RANK recognition** | ❌ ~80% wall | not reliable enough — see below. |

### Chip/pot OCR (#4) — the reliable win

Poker numbers are **white digits on a coloured plate** among gold labels/border, where
Otsu thresholding fails. `HudReader.read(white=True)` isolates white (bright +
low-saturation, V≥135) and **strips the plate's full-width top-edge highlight** (a
near-full-width white row that otherwise merges digit tops and bleeds into glyph
crops — this was the reliability fix), then reuses the existing digit
split + match. Poker digit templates live in `data/poker_digits/` (gitignored).
Number ROIs are in `config/regions.json` → `poker` (pot/chips/bet/total_bet).

### Card reading — why it doesn't work (exhaustively established)

Card slots are fixed (2 hole + 5 board, ROIs in config `poker`); poker cards are flat
and separated (NOT blackjack's tilted cascade). We captured 263 frames, labeled 97
cards (all ranks), and tried: template matching (rank 75%), raw-pixel SVM (62%),
HOG+SVM (corner 71% / **whole-card 80%**), a CNN with augmentation (corner 53% /
whole-card 75%), and **temporal voting** (57%→57%, no gain — errors are *systematic*,
not random). Findings:

- **The labels are correct** (verified by montaging every misclassification) — it is
  NOT a labeling problem.
- **Whole-card crops beat corner crops** (80% vs 75%) — the corner was too small and
  contaminated. But that only buys +5%.
- The residual errors are **contamination** (result banners painted over cards,
  overlapping neighbour cards) + **too few / thin samples** (a single `5`) + genuine
  glyph ambiguity at ~30px. Adding compute (sklearn, a CPU CNN) did NOT help — the
  ceiling is in the data/capture, not the model.
- **The math kills it:** poker needs ~97%/card (7 cards/hand, and unlike blackjack
  there is NO HUD total to cross-check against). Even an optimistic 90% gives
  0.9⁷ ≈ 48% fully-correct hands. 80% is nowhere near, and there's no cheap path up.

**Conclusion:** screen-scraped poker card reading on this game is not reliable enough
for trustworthy hand advice, and very likely never will be.

## The realistic tool — semi-automatic

The cards can't be auto-read *reliably*, but a guess-and-correct loop sidesteps
that — the screen seeds the input, the human is the safety net:
- The tool **auto-detects your 2 hole cards** and shows them for you to confirm or
  correct; you type the board as it comes (live overlay or the manual CLI).
- The tool auto-reads the **pot, street, active-opponent count and to_call** and
  shows equity + pot odds + a fold/call/raise call.

### Hole-card auto-detection (advisory) — `vision/poker_cards.py`

A best-effort `HoleCardReader` seeds the overlay with the hole cards; the hero
confirms or fixes them (a typed hand locks until the next deal re-arms it). It is
deliberately **advisory, not authoritative** — measured on the labeled corners:
- **suit colour** red/black ≈ 95% (ink-pixel redness) — the strong signal, shown
  prominently so a wrong rank/suit is easy to spot.
- **rank** ≈ 50-60% (nearest-exemplar match vs the labeled corner crops) and
  exact within-colour suit ≈ weak — i.e. expect to correct roughly half of hands.

That's still a win: a seeded guess is never worse than typing (right → zero
keystrokes, wrong → type as before). To improve it, grow the exemplar library by
labeling more captures (`label --poker`); the rank ceiling is ~75-80% (above).

That's a genuinely useful poker assistant that sidesteps the one thing the screen
won't give us. **Built** (`app/live.py poker`):

- **`to_call`** = max *active*-opponent Bet − hero Bet (floored at 0).
  `vision/poker.py` reads each opponent's Bet plate with the white-glyph HUD
  reader (`opp_bet` ROIs, validated against `data/poker`) and detects folds
  label-free: a folded seat keeps a "Fold" banner with a unique **cyan** double-
  chevron icon (Call = green, Raise = red), so a saturated-cyan pixel count in the
  `opp_banner` box separates folded from active cleanly (whole-session check: ≤1 px
  non-fold vs 150–250 fold, no overlap). A folded player never holds the max bet,
  so this also gives the right `to_call`; the active count feeds equity's opponent
  number.
- **Overlay glue** — `live.py poker` runs semi-auto: a background stdin thread
  takes your `hole | board` (with `+ Td` to deal a card), each frame auto-reads
  `table_state` (pot / street / active opps / to_call) and shows the advice. The
  Monte-Carlo equity is cached on (hole, board, opp) so only the cheap pot-odds
  decision recomputes per frame (`advisor.decide`).

## Dependencies note

`scikit-learn` and `torch` (CPU) were added to **prove** the card-reading wall is a
data/capture limit, not a tooling gap. They are not used by any shipping code. If the
semi-auto path is taken and nobody pursues a large poker-card dataset, they can be
removed to keep the project lean.

## Open issues / next

- **#4** Poker equity overlay + chip OCR — **done** (chip/pot OCR, opponent
  bet + fold reading → to_call, and the semi-auto live overlay).
- **#5** tilted/overlapping fan recognition — N/A for poker (flat cards); the poker
  card wall is contamination + sample size, a different problem.
