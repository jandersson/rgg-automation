# Detection mechanisms — algorithm notes

Every way this project reads the screen, spelled out at refresher depth:
the assumed reader has seen image processing and a bit of ML before but
doesn't remember the specifics. Companion to **POKER.md** (the poker
track's status) and **ARCHITECTURE.md** (the pipeline); this file is the
*how the eyes actually work* reference.

The screen-reading splits cleanly into two problems with very different
difficulty:

- **Fixed glyphs** — HUD digits (blackjack "Total" badges, poker pot/bet
  plates) and the blackjack felt rank. The game renders these from fixed
  sprites at a fixed resolution, so the *same glyph is pixel-identical
  every time*. This is the easy problem; template matching nails it.
- **Card rank + suit off the felt** — the hard problem. Cards are bigger,
  occasionally **obscured** (banners, tooltips, overlapping neighbours),
  and there are 52 of them. This is where the interesting machine-learning
  story lives, and where the project spent most of its effort.

Code lives in `judgment_assist/vision/` (`hud.py`, `poker.py`,
`poker_cards.py`, `locate.py`, `recognizer.py`).

---

## Template matching — `cv2.matchTemplate` (HUD glyphs)

**The mental model:** slide a small reference image over the target and
find where it lines up best.

**The algorithm (normalised cross-correlation):** for a template \\(T\\) and
an image patch \\(I\\) at offset \\((u,v)\\), the match score is

$$\text{NCC}(u,v) = \frac{\sum_{x,y} \big(T(x,y) - \bar T\big)\big(I(u{+}x, v{+}y) - \bar I\big)}{\sqrt{\sum (T-\bar T)^2 \, \sum (I-\bar I)^2}}$$

The mean-subtraction and the denominator make it invariant to brightness
and contrast shifts, so the same digit matches whether the plate is lit
brightly or dimly. Score is in \\([-1, 1]\\); \\(1\\) is a perfect match.

**Why it's near-100% for HUD glyphs:** the glyphs are sprite-rendered, so
the template *is* the thing being matched — no within-class variation at
all. We capture the template library once from the running game
(calibration), then every read is a lookup.

**Where it broke — card reading (the wall).** Template matching a card's
rank/suit failed (~75%). Cards aren't pixel-identical the way digits are:
the corner index is contaminated by the centre pip and the neighbour
card's index, result banners get painted over them, and at ~30px the
glyphs are genuinely ambiguous. Template matching has *no notion of
"close but contaminated"* — it just reports the best raw correlation,
which a banner streak can dominate. This is what kicked off the ML
detour below. (See POKER.md for the exhaustive record.)

**The white-digit twist (`hud.py`).** Poker numbers are *white* digits on
a coloured plate, where Otsu thresholding fails. `HudReader.read(white=True)`
isolates white (bright + low-saturation, V≥135) and strips the plate's
full-width top-edge highlight (a near-full-width white row that otherwise
merges digit tops) before the digit split + template match. That fix is
what made pot/bet OCR reliable.

---

## Colour / ink-redness — `_is_red` (the one reliable card signal)

**The mental model:** is the ink on this card red or black? That single
bit is the most trustworthy thing we can read off a card.

**The algorithm:** take the suit-pip patch, find the *ink* pixels (darker
than the local mean), and measure their redness:

$$\text{redness} = r - \tfrac{g + b}{2} \quad\text{averaged over ink pixels only}$$

Averaging over ink pixels *only* matters — the white card body would
dilute a whole-region mean toward grey. A threshold (>10) separates red
(hearts/diamonds) from black (clubs/spades) at ~95–100%.

**Why it earns its keep — colour-gating.** Reading the exact suit is hard
(c vs s, h vs d), but the *colour* is easy and reliable. So the suit
classifier is **colour-gated**: it only ever picks among the two suits of
the detected colour. The read can never contradict the reliable signal —
a card that's clearly red is never labelled clubs. This is a recurring
trick: *let an easy, reliable measurement constrain a hard, unreliable
one.*

**A gotcha we hit (and dropped):** using colour to *validate* a label
(label says hearts → ink should be red) sounds great as a mislabel
detector, but our region-on-the-stored-crop was wrong and produced 29
one-directional false positives. The labels were right; the colour read
was the broken thing. Lesson: a cross-check is only worth running if the
independent signal is *more* trustworthy than the thing it's checking.

---

## Label-free geometry gates — `card_present`, `board_count`, fold detection

These read *state* without reading *content* — pure geometry + simple
pixel statistics, no templates or training.

**`card_present` (`poker.py`).** Is a face-up card in this corner ROI? A
real card corner is mostly bright white card-face with a small dark
glyph; an empty slot is green felt, a result banner is dark, an opponent's
back is red. Test: >55% of pixels are "white" (HSV-gated) **and** mean
grey > 140. Two cheap thresholds, robust.

**`board_count` / `street`.** Count how many of the 5 board slots pass
`card_present` → 0/3/4/5 → preflop/flop/turn/river. The street is read
from geometry, label-free, and it's reliable — which is why the overlay
can always tell you *which* street you're on even when it can't read the
cards.

**Fold detection (cyan chevron).** A folded seat keeps a "Fold" banner
with a distinctive **cyan** double-chevron icon; every other action uses a
non-cyan icon (Call green, Raise red). Counting saturated-cyan pixels in
the banner box separates folded from active cleanly — across a 697-frame
session the count was ≤1 for non-folds and 150–250 for folds (no
overlap). This gives the active-opponent count (which feeds equity) and
the to-call price, again label-free. The lesson mirrors colour-gating:
*find the one feature that's unambiguous and lean on it.*

---

## HOG + LinearSVC — the shipping card reader (`poker_cards.py`)

This is the production hole/board reader. **Advisory** — the human
confirms/corrects it — but the best non-human option that ships.

### The mental model

Describe each card by the *shape of its edges* (a HOG descriptor), then
draw linear boundaries between the 13 ranks in that feature space.

### HOG — Histogram of Oriented Gradients

Resize the whole card to a fixed window (64×96), compute the gradient at
every pixel, and for each small cell build a histogram of gradient
*orientations* weighted by magnitude. Concatenate all cells' histograms
into one vector.

Why it works for glyphs: a "K" and an "8" differ in their *edge
structure* (where strokes go, at what angles), and HOG captures exactly
that while being robust to small brightness/position shifts (it's
gradients, not raw pixels, pooled over cells). It's the classic
pedestrian/digit descriptor for a reason.

### LinearSVC — linear support vector classification

A linear SVM finds, for each pair of classes, the hyperplane that
separates them with the widest margin:

$$\min_{w,b}\; \tfrac{1}{2}\|w\|^2 + C \sum_i \max\big(0,\; 1 - y_i(w^\top x_i + b)\big)$$

The first term widens the margin; the hinge-loss term penalises
misclassifications; \\(C\\) trades them off. "Linear" because in
HOG-feature space the classes are roughly linearly separable, so we don't
need a kernel — which keeps it *fast to fit*.

### Why this exact stack

- **Whole card beats the corner.** The corner crop is contaminated by the
  centre pip and the neighbour's index; a whole card is clean. (+5%.)
- **Colour-gated suit.** Rank via the SVM, colour via `_is_red`, suit =
  best same-colour suit. The suit never fights the colour.
- **It hot-refits on correction.** This is the killer property: when you
  correct a card in the GUI, the new crop is added and the SVM **re-fits
  in milliseconds** (`add_exemplar` → `_fit`). The reader literally gets
  better as you play. No GPU, no training loop — `LinearSVC.fit` on a few
  hundred HOG vectors is instant.

### The numbers (and a sharp caveat — see "the leakage trap")

On the labelled library, plain 5-fold CV: **~90% rank**. That looked
competitive with everything we tried — until grouped CV revealed most of
it was leakage (below).

---

## CNN from scratch — why "old tech" looked like it won

The natural next step: train a small ConvNet on the card crops. Across
many seeds it landed at **~90% rank with light augmentation** — i.e. a
*tie* with HOG+SVM, not a win, and with much higher variance.

**Why it didn't beat HOG:** 138 labelled crops across 13 classes is
*tiny* for a from-scratch CNN. The net has enough capacity to fit the
training set (train acc 95–100%) but not enough data to learn
generalisable filters better than HOG's hand-designed gradient features.
For small, fixed-pose, well-structured glyph data, HOG+SVM is genuinely
near-optimal — classic features shine exactly when data is scarce.

This is the "old tech wins" result that (correctly) felt suspicious. Two
things were going on, and both got resolved below: the from-scratch CNN
was *underpowered* (→ transfer learning), and the comparison itself was
*rigged by leakage* (→ grouped CV).

---

## Augmentation — what helps and what hurts (the key lesson)

Augmentation only helps when it **matches the variation the model will
actually see at test time.** This isn't a platitude here — we measured it,
and the naive intuitions were wrong:

- **Rotation / flips — HURT** (90% → ~70%). Intuition says "rotate to
  generalise". But the cards sit in a **fixed ROI** — same position,
  orientation, scale, every hand. Rotation/flip invariance is something
  the model *never needs*, so forcing it to learn it from 138 samples
  wastes capacity and makes it underfit the poses that actually occur.
  (180° is *geometrically* label-preserving for a point-symmetric card,
  but it still doesn't occur in the fixed ROI, so it doesn't help.)
- **Light photometric (brightness/contrast/small shift) — neutral/slight
  help.** This matches the real variation: lighting and sub-pixel ROI
  jitter. It's what tied HOG and what the ResNet trains on.
- **Occlusion (Cutout / Random-Erasing) — the principled bet.** Blanking
  random rectangles simulates a banner/tooltip/neighbour covering part of
  the card — which *is* the live failure mode (POKER.md's "contamination").
  Unlike geometric aug, it matches the test distribution. (Experiment in
  progress; results appended below.)

Corollary: aug strength must match model capacity. The aggressive
photometric aug that *hurt* the tiny from-scratch net (90→74%) was
*shrugged off* by the pretrained ResNet (which has robust low-level
filters already).

---

## Transfer learning — pretrained ResNet (the breakthrough)

**The mental model:** don't learn edge/texture filters from 138 images —
*borrow* them from a network already trained on a million, and only
re-learn the final card-specific decision.

**The recipe that worked:** `torchvision` ResNet18/34 pretrained on
ImageNet, replace the final fully-connected layer with a 13-way head,
fine-tune the whole thing at **224px** input (near the pretrained native
resolution), with cosine LR decay, label smoothing (0.1), and *light*
augmentation. Plus **test-time augmentation (TTA)** — average the softmax
over the clean view and a few light-aug views; a free ~+2 points.

**Why it wins on small data:** ImageNet features (edges, corners,
textures) transfer directly — a card glyph is built from the same
primitives. The net starts ~90% of the way there and only fine-tunes the
last mile, so 138 images is plenty. This is the standard small-data move,
and it's exactly what the from-scratch CNN couldn't do.

**The levers, measured:**

| Change | Effect |
|---|---|
| Resolution 96×128 → 224 | ResNet18 93 → 95% |
| Full fine-tune vs freeze-early | 95% vs 87% (freezing starves it) |
| TTA | +~2 pts everywhere |
| ResNet18 → ResNet34 | 95 → 98% |

**Stacked best (ResNet34 @224 + TTA):** ~99% on plain CV — and, crucially,
it *holds up* under leakage-free grouped CV (next section).

---

## The leakage trap — why grouped CV is the only honest number

**The trap:** the crop library has **multiple frames of the same physical
card** (e.g. consecutive frames of one K♦ on the board). Capture-time
dedup drops *near-identical* frames but keeps merely-similar ones, so one
physical card can leave several crops. In plain k-fold CV those land in
**both** train and test folds — the model is tested on a card it
near-already-memorised. **That inflates every CV number.**

**The fix — grouped cross-validation.** Cluster crops into "physical card"
groups (union-find: same rank+suit *and* visually near, by the dedup
signature distance), then split with `StratifiedGroupKFold` so a whole
group stays in one fold. Now the test set is genuinely *unseen* cards.

**The result was decisive — and reversed the ranking:**

| Model | Plain 5-fold (leaky) | Grouped (honest) |
|---|---|---|
| HOG + LinearSVC | 90.0% | **68.5%** |
| ResNet34 @224 (+TTA) | ~99% | **97.5–98.2%** |

(146 crops collapsed to **76 physical-card groups** — 112 crops were
duplicate frames, so the leakage was huge.) HOG's "90%" was *mostly
memorising near-duplicate frames*; on a genuinely new card it's barely
better than guessing among lookalikes. The ResNet barely dropped — it
*actually generalises*. The takeaway: **always group by the real unit of
variation (the physical card), or you're measuring memorisation.**

Caveat that remains: even the grouped number is on *clean* crops. Robustness
to **obscured** cards is the separate axis the Cutout experiment targets.

---

## kNN label-consistency — the mislabel finder (`suspect_labels`)

Not a card reader — a **data-quality** tool for the Labels tab's review
pass.

**The mental model:** a crop whose label disagrees with its visual
look-alikes is suspect.

**The algorithm:** for each labelled crop, find its \\(k\\) nearest
neighbours in HOG-feature space; if the crop's rank isn't the
neighbourhood's majority, flag it and suggest the plurality rank.

**Honest verdict (measured by eye on the real data):** it mostly surfaces
*systematic lookalikes* (9↔T, J↔K) that are correctly labelled, not actual
mislabels — the backlog is largely clean. So it's framed in the GUI as
"hard cases to double-check", **not a verdict**. The by-label *sort*
(twins adjacent, so an outlier pops) turned out to be a more reliable way
for a human to spot a genuine mislabel than any auto-flagger.

---

## Cheat-sheet — when each mechanism is the right tool

- **Fixed sprite glyph (digit, badge):** template matching. Near-100%, no
  training, instant.
- **One reliable bit (card colour, fold/active):** a hand-designed pixel
  statistic + threshold. Use it to *gate* the hard classifier.
- **Card rank, ships today, must hot-refit on correction:** HOG +
  LinearSVC. ~68% on truly new cards, but instant retraining and no GPU.
- **Card rank, highest accuracy, GPU acceptable:** fine-tuned pretrained
  ResNet (224, TTA). ~98% on new cards, but a heavy dependency and no
  millisecond refit.
- **Measuring any of the above:** group by physical card or the number is
  a lie.
- **Finding bad labels:** sort by label and use your eyes; the kNN flag is
  a hint, not an oracle.
