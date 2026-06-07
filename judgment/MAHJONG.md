# Mahjong — track status & rules primer

Judgment's **Mahjong** (and **Wareme Mahjong**) minigame is **Japanese Riichi
Mahjong**. This track is **Phase 0**: a pure, unit-tested *efficiency advisor*
(no screen capture yet), built brains-first like poker/blackjack were.

> **What it does today.** Type the tiles you hold; it tells you how far you are
> from a win and which tile to throw to advance fastest.
> **What it doesn't yet.** No vision (you type the hand), and no yaku/dora/defence
> weighting — it optimises pure speed. See *Roadmap* at the bottom.

---

## 1. The rules, just enough to use the advisor

Four players. **136 tiles**: three number suits — **m**an (萬/characters), **p**in
(筒/circles), **s**ou (索/bamboo), each 1–9 — plus **honors**: 4 winds (East South
West North) and 3 dragons (White Green Red). Four copies of every kind → 34 kinds.

The loop is: you hold **13 tiles**; on your turn you draw a 14th, then **discard
one**. So every turn is really one question — *what do I throw away?* That is
exactly what this advisor answers.

**A winning hand = 4 sets + 1 pair** (14 tiles):
- a **set** is either a **triplet** (three identical, e.g. `555p`) or a **run**
  (three consecutive in *one* number suit, e.g. `678s`). Honors can't run.
- the **pair** (the "head") is two identical tiles.

Two ways to finish: **tsumo** (you draw your winning tile) or **ron** (you claim
an opponent's discard). You also need at least one **yaku** (a scoring pattern)
to win at all — the most reliable beginner yaku is **riichi** itself.

**Riichi**: when your hand is closed (no claimed tiles) and **one tile from
winning** (*tenpai*), you may declare riichi — bet 1,000 points, flip your hand
face-down-committed, and gain a yaku plus bonus chances. It's the backbone of a
beginner's offence.

**Dora** are bonus tiles (an indicator points at them) that add value but are
*not* a yaku — they don't let you win, they just make a win bigger.

### The two key numbers this tool computes

- **Shanten** — how many tile-swaps from *tenpai* (ready). `0` = tenpai,
  `1` = one away from ready, `-1` = already a complete hand.
- **Ukeire** ("acceptance") — at a given shanten, *which* tiles improve the hand,
  and how many of them are still live. Bigger ukeire = you advance sooner.

The advisor ranks each possible discard by **(lowest shanten, then highest
ukeire)** — the standard efficiency rule.

### Shape vocabulary (why it picks what it picks)

| Shape | Example | Waits on | Live tiles |
|-------|---------|----------|------------|
| **Ryanmen** (open two-side) | `56m` | 4m, 7m | up to **8** |
| **Kanchan** (closed middle) | `13p` | 2p | up to 4 |
| **Penchan** (edge) | `89s` | 7s | up to 4 |
| **Pair → triplet** | `99p` | 9p | up to 2 |

A ryanmen accepts twice what a kanchan/penchan does, so when the advisor keeps
`56m` and throws a `13p`, that's why.

---

## 2. The variants you saw in-game

There's **one ruleset** (Riichi). The "variants" are really:

- **Regular vs Wareme Mahjong** — *Wareme* randomly marks one player each hand who
  **pays and receives double**. It changes *scoring/payouts only*, never which
  tile to discard — so it doesn't affect this advisor.
- **Full vs Half game** — match length (East+South ≥8 hands vs East-only ≥4).
- **Rule toggles** — *Kuitan* (open all-simples allowed), *Red Dora* (akadora),
  optional 2-han minimum.

None of these change shanten/ukeire, so the efficiency brain is variant-agnostic.

---

## 3. Using it

From `judgment/`, with `uv`:

```
# one-shot — 14 tiles → ranked discards:
uv run python -m judgment_assist.app.cli mahjong --hand "56m 99m 456p 789p 123s 1z"

# one-shot — 13 tiles → shanten + ukeire:
uv run python -m judgment_assist.app.cli mahjong --hand "123m 456m 789m 123p 9s"

# interactive REPL (type hands; 'seen <tiles>' marks dead tiles; 'quit'):
uv run python -m judgment_assist.app.cli mahjong
```

**Notation.** Digits then a suit letter, any order, spaces optional:
`123m` = 1–3 man, `99s` = pair of 9 bamboo. Honors use the **z** block:
`1z`=East `2z`=South `3z`=West `4z`=North `5z`=White `6z`=Green `7z`=Red.
So the thirteen orphans are `19m 19p 19s 1234567z`.

`--seen` / `seen <tiles>` lets you mark tiles already gone (your discards, the
dora indicator, opponents' pond) so the ukeire count is honest rather than an
optimistic upper bound.

---

## 4. How the brain works (code map)

| File | What |
|------|------|
| `mahjong/tiles.py` | 34-count-array model; riichi-notation parse/format |
| `mahjong/shanten.py` | shanten over **standard / chiitoitsu / kokushi** forms |
| `mahjong/efficiency.py` | ukeire (acceptance) + ranked discard recommendation |
| `app/cli.py` (`mahjong`) | the manual advisor / REPL |

Shanten enumerates each possible head pair (plus the headless case) and DFS-
decomposes the rest into melds + partials, capped at four blocks — then takes the
best of the standard hand, seven-pairs (*chiitoitsu*), and thirteen-orphans
(*kokushi*) forms. Ukeire sweeps all 34 draws and keeps those that lower shanten.
Tests: `tests/test_mahjong_{tiles,shanten,efficiency}.py`.

---

## 5. Roadmap (deferred)

1. **Vision** — read the hand off screen. Promising: your 13–14 hand tiles are
   large, upright, evenly spaced, never obscured → far friendlier to template
   matching than poker's angled felt cards (the documented poker wall). 34 clean
   sprite classes. Discard ponds and the dora indicator are also upright.
2. **Honest ukeire from the pond** — auto-feed `seen` from discards + dora.
3. **Yaku / dora awareness** — value-weighted discards, not just speed.
4. **Defence** — safe-tile (genbutsu/suji) reading when an opponent declares
   riichi, and a push/fold hint. The genuinely hard part; research-grade.
5. **Overlay** — float the recommendation over the game like the poker launcher.
