---
title: RGG automation — docs
---

# RGG automation — docs

Companion notes for the screen-reading move advisor at
[github.com/jandersson/rgg-automation](https://github.com/jandersson/rgg-automation).
The advisor watches *Judgment*'s poker and blackjack minigames and shows
the best move (advice only — it never sends inputs).

## Explainers

- **[detection.md](detection.md)** — refresher-depth notes on every
  screen-reading mechanism: template matching, colour-gating, the
  HOG+SVM card reader, from-scratch vs transfer-learned CNNs, the
  augmentation lessons, the data-leakage trap (grouped CV), and the
  mislabel finder. Ends with a when-to-use-what cheat-sheet.

## In-repo references (rendered on github.com)

- **[POKER.md](https://github.com/jandersson/rgg-automation/blob/main/judgment/POKER.md)**
  — the poker track's status: what works, what doesn't, the semi-auto
  launcher, and the documented card-reading wall.
- **[ARCHITECTURE.md](https://github.com/jandersson/rgg-automation/blob/main/judgment/ARCHITECTURE.md)**
  — the capture → vision → state → advisor → overlay pipeline and the
  build phases.
