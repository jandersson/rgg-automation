# AGENTS.md — working instructions for coding agents

Repo: **rgg-automation** — a move advisor for *Judgment*'s minigames. It's a
monorepo; the active project is **`judgment/`** (Texas Hold'em poker + blackjack).
Advice only — it never sends inputs to the game.

## Commands (run from `judgment/`)

Everything uses `uv`. Run from the `judgment/` directory:

- Tests: `uv run pytest -q`
- Launch the poker app (GUI): `uv run python -m judgment_assist.app.launcher`
- Standalone live overlay: `uv run python -m judgment_assist.app.live poker`
- Manual advice (no calibration): `uv run python -m judgment_assist.app.cli poker --hole "Ah Kh" --board "Qh 7h 2h" --opp 2`
- Mahjong efficiency advisor (brains-only, no capture): `uv run python -m judgment_assist.app.cli mahjong --hand "56m 99m 456p 789p 123s 1z"`

## Conventions

- **Branch:** work directly on `main`. No `claude/<slug>` branches or PRs unless asked.
- **Commits:** Conventional Commits — `type(scope): summary` (feat/fix/refactor/docs/chore). Commit per logical piece. End every message with the `Co-Authored-By:` trailer.
- **Pushing:** do **not** push unless explicitly asked.
- **Tests:** keep them green. Add/adjust tests with behaviour changes.
- **Vision changes:** validate against captured frames in `data/poker` before wiring them into the live path.

## Gotchas

- **Learning banks crops.** Don't run dev/test sessions with learning ON against the live table — confirms/corrections write crops to `data/poker_cards`.
- **Stray live processes resurrect deletions.** A running `judgment_assist.app.live` / launcher holds `labels.json` in memory and rewrites the whole file on its next save. Kill all such processes before editing or scrubbing `data/poker_cards/labels.json`, or your edits get clobbered.
- **`reviewed` flag = Labels-tab second pass only.** Live play (confirm/correct) saves labels but does not mark them reviewed.
- **Gitignored data:** `data/poker_cards`, `data/poker_digits`, `data/poker`, etc. hold crops/frames and are not committed — only code and the labeled-task format are.

## Docs

- `judgment/POKER.md` — poker track status (what works, what doesn't, the launcher).
- `judgment/MAHJONG.md` — Mahjong (Riichi) track: rules primer + the shanten/ukeire efficiency advisor (Phase 0, brains-only).
- `judgment/ARCHITECTURE.md` — capture → vision → state → advisor → overlay pipeline.
- `docs/detection.md` — how every detection mechanism works (template/HOG/CNN/transfer/leakage); rendered on GitHub Pages.
