# Poker (Texas Hold'em) — status & findings

Honest record of the poker track. **Bottom line (updated 2026-06-06): the brain
works, the pot/street/fold eyes are reliable, and card reading — long "the wall" —
is now solved by a transfer-learned CNN.** A fine-tuned ResNet34 reads ~98% rank
on new cards and ~96% on obscured cards (leakage-free grouped CV), and held up
live (~1 correction over several hands). It ships as the **default** reader; the
HOG+SVM reader (which learns from your corrections as you play) is selectable. The
"card reading can't work" sections below were true for HOG / from-scratch models
and are kept for the record — read them with the update note in mind. Mechanism
details: `docs/detection.md`.

> **Update (2026-06-06) — the wall came down.** The conclusion below ("not reliable
> enough, very likely never will be") was reached with template matching, SVMs, and
> a from-scratch CNN, and with plain k-fold CV. Two things changed it:
> 1. **The old ~80–90% numbers were inflated by data leakage** — the crop library has
>    many near-duplicate frames of the same physical card, which landed in both train
>    and test folds. Under *grouped* CV (same physical card kept in one fold) HOG
>    collapses to **68.5% rank** on new cards (and ~45% on obscured) — it was largely
>    memorising frames.
> 2. **Transfer learning clears it.** A pretrained ResNet34, fine-tuned at 224px with
>    light aug + TTA, reads **~98% rank / ~96% obscured** under the same grouped CV,
>    and ~1-correction-over-several-hands live. The from-scratch CNN was the weak
>    link, not the task. Shipped as `vision/cnn_cards.py` (`CnnCardReader`), default
>    in the launcher, weights in `models/cnn_card.pt` (Git LFS).

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
| **Suit recognition** | reliable | colour red/black ≈ 100% (ink-pixel redness), colour-gated; exact suit from the reader's suit head/classifier. |
| **Card RANK recognition** | ✅ CNN ~98% / HOG 68.5% | leakage-free grouped CV on NEW cards. CNN (ResNet34, default) reads ~96% even on obscured cards; HOG ~45% obscured. HOG is the learns-as-you-play fallback. Numbers + the leakage story: see the update note above and `docs/detection.md`. |

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

**Conclusion (SUPERSEDED — see the update note at the top):** with template
matching / SVMs / a from-scratch CNN this read ~80%, not enough. But that ceiling
was the *model and the leaky evaluation*, not the task: a transfer-learned ResNet34
reads ~98% / ~96%-obscured (leakage-free), so screen-scraped card reading IS
reliable enough now. The "thin samples / contamination" point still holds for the
HOG reader and for clean training data, which is why obscured examples and the CNN
both mattered.

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
**advisory, not authoritative**, but much better than the old corner reader —
**whole-card** beats corners because the corner crop is contaminated by the centre
pip and the neighbour's index, while a hole card is clean and separated. Measured
leave-one-out on the labeled cards:
- **whole-card HOG + LinearSVC**: rank ≈ **74%**, suit ≈ **84%** on hole cards
  (vs the old corner template's ~47% rank) — beats POKER.md's earlier 80%
  whole-card HOG+SVM figure, and improves as the library grows.
- **suit colour** red/black ≈ 95% (ink-pixel redness) — the strongest single
  signal; the suit is **colour-gated** (the SVM only picks among suits of the
  detected colour), so the read never contradicts the colour.

Geometry: whole-card ROIs are measured per slot (hole ~278×400, the smaller board
~250×300) and size-normalised to a 64×96 HOG window. Presence/colour still use the
bright corner. `recrop_library_to_whole` re-crops the labeled corners to whole
cards from the source frames (labels transfer by `frame#slot`).

A seeded guess is never worse than typing (right → zero keystrokes, wrong → type).

**It learns from your corrections** (`TrainingWriter`, on by default; `--no-learn`
to disable). Confirming a hand (bare Enter) or correcting it (typing) saves each
face-up card's **whole-card crop** with its now-known label into `data/poker_cards`
— the same crop+`labels.json` format `label --poker` produces — and hot-adds it,
**refitting the SVM**, so detection improves immediately and more on the next
launch. Captured from the last LIVE frame, not the current one — so a correction
typed while the game is paused/tabbed-away still grabs good pixels. Typed board
cards are captured too; crops are deduped so a static hand isn't re-saved. Ordinary
play becomes labeling: the more you use it, the higher rank climbs.

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

`scikit-learn` is now **shipping**: the hole-card reader's whole-card rank/suit
classifiers are `LinearSVC`s (above). `torch` (CPU) was only ever used to *prove*
the card-reading wall during the CNN experiments and is **not used by any shipping
code** — it can be dropped to slim the install.

## Status — 2026-06-06 (launcher era)

The whole thing is wired and in daily use. Architecture:

- **`app/launcher.py` is the app for poker.** It runs the advisor **in-process**
  (no subprocess), shows a **display-only** borderless overlay (`SuggestionOverlay`,
  `master=`) over the game, and hosts the **Corrections** panel: per-card pickers in
  two styles (Dropdowns / Card grid, `corr_mode` radio), a **Confirm hand** button,
  a **Log** pane (stdout teed in), and a status line. Single-instance mutex (one
  launcher, one overlay). Blackjack still launches as a subprocess.
- **`app/live.py`** holds `PokerAdvisor` (state + detection + `text()`), the tk loop
  (`_tick` in the launcher; `run()` for the standalone CLI), `grab_frame` (returns
  None when the game window isn't found — never reads the desktop), `_screen_dimmed`
  (PAUSED), and the global confirm hotkey (`_key_poller`, default **Insert**).
- **Detection (`vision/poker_cards.py`):** whole-card HOG + LinearSVC, colour-gated
  suit. Reads **hole and board**. ~74% rank / ~84% suit (hole, LOO); lower on fresh
  sessions; advisory + corrected by the human.
- **Learning:** `set_hole/set_board` only set state (no auto-bank). Banking is
  explicit: `bank_card(kind, idx, card)` for ONE corrected card, `confirm()` for the
  whole verified hand → `TrainingWriter` saves the whole-card crop + hot-adds to the
  reader (SVM refit). Library `data/poker_cards` (gitignored).

**Gotchas learned the hard way:** stray/old overlay processes hold `labels.json` in
memory and resurrect deletions — kill ALL `python -m judgment_assist.app.live` procs
before scrubbing `live*` entries. Don't run dev sessions with learning on against
the real table (they bank crops). Corrections only valid when Judgment is actually
on the table (else the read is garbage).

**Last bug fixed (1aa36c3):** board could stick on "reading the board" when a
flicker on a corrected slot blocked new community cards — now stability is over
non-fixed slots + a patience fallback. **Watch next:** verify board detection
accuracy on the live table (it misreads, e.g. 5♠→9s, on fresh sessions — the user
corrects it, which trains it).

## Open issues / next

- **#4** Poker equity overlay + chip OCR — **done** (chip/pot OCR, opponent
  bet + fold reading → to_call, and the semi-auto live overlay).
- **#5** tilted/overlapping fan recognition — N/A for poker (flat cards); the poker
  card wall is contamination + sample size, a different problem.
