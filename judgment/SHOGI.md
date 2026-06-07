# Shogi — track status & rules primer

Judgment's **Outdoor Shogi** (full matches) and **Puzzle Shogi** (tsume) minigame
is standard Japanese chess. This track is an **engine-driver foundation**: a
state model + a pure-Python forced-mate solver + a pluggable **USI** engine
driver. Strong play needs a real engine, so we drive one rather than reinvent it.

> **What it does today.** Type a position (SFEN) and moves; it reports check/mate
> status, finds any **forced mate** exactly (no engine needed), and — with a USI
> engine configured — gives the best move in any position.
> **What it doesn't yet.** No vision (you type the position) and no overlay. See
> *Roadmap*.

---

## 1. The rules, just enough to use the advisor

Two players (**Black/sente** moves up the board, **White/gote** moves down) on a
**9×9** board. You win by **checkmating** the enemy King. Two things make shogi
its own game, not just chess:

- **Drops.** A captured piece switches sides and goes to *your hand*; instead of
  moving a board piece, you may **drop** a hand piece onto (almost) any empty
  square as your move. Nothing leaves the game — attacks rebuild constantly.
- **Promotion.** A piece that moves into, within, or out of the **far three
  ranks** (the enemy's third) may flip to a stronger promoted side.

The pieces (and how they promote):

| Piece | Moves | Promotes to |
|-------|-------|-------------|
| King (K) | one square any direction | — |
| Rook (R) | any distance orthogonally | **Dragon** (+R): rook + one-step diagonal |
| Bishop (B) | any distance diagonally | **Horse** (+B): bishop + one-step orthogonal |
| Gold (G) | one step orthogonally + forward diagonals | — |
| Silver (S) | one step diagonally + straight forward | **+S**, moves like Gold |
| Knight (N) | jumps two-forward-one-sideways (forward only) | **+N**, like Gold |
| Lance (L) | any distance straight forward | **+L**, like Gold |
| Pawn (P) | one step straight forward | **+P** (tokin), like Gold |

Drop restrictions worth knowing: no two unpromoted pawns on one file
(*nifu*), and you can't drop a pawn to give *immediate* checkmate (*uchifuzume*).
In-game, press **R1** to see how a selected piece moves; once you befriend
**Onodera (Ch. 5)**, the *Basics of Shogi* item shows a best-move hint for SP —
this tool is the external version of that.

### The two things this tool computes

- **Forced mate (tsume).** Given the attacker to move, is there a sequence that
  checkmates no matter how the defender replies? Exact, by exhaustive search of
  *checking* lines. This is the whole point of **Puzzle Shogi** (mate-in-N) and
  also flags a kill in a live match.
- **Best move (positional).** Everything that isn't a forced mate needs
  judgement — material, king safety, shape. That's the **USI engine**'s job.

---

## 2. The modes you see in-game

- **Outdoor Shogi** — full matches. *Ranked* (rising opponent skill) and
  *Challenge* (you start handicapped). Venue rotates around Kamurocho back-lots by
  time of day.
- **Puzzle Shogi** — a fixed position, mate in a set number of moves. The
  pure-Python solver here handles these with no engine binary.

---

## 3. Notation

- **SFEN** — one-line position. Opening:
  `lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1`.
  Ranks a→i top to bottom, files 9→1 left to right. **Upper-case = Black**,
  lower-case = White. Trailing fields: side to move (`b`/`w`), pieces in hand,
  move number. Promoted pieces are `+` prefixed (`+R` = Dragon).
- **USI moves** — `7g7f` (from→to), `7g7f+` (promote), drops `G*5b`
  (drop a Gold on 5b). Squares are file(1–9)+rank(a–i).

---

## 4. Using it

From `judgment/`, with `uv`:

```
# forced-mate / Puzzle Shogi — no engine needed:
uv run python -m judgment_assist.app.cli shogi --sfen "4k4/9/4G4/9/9/9/9/9/4K4 b G 1"
#   -> G*5b   (forced mate in 1)

# play moves from a position:
uv run python -m judgment_assist.app.cli shogi --move "7g7f 3c3d"

# full-match advice with a USI engine (see §5):
uv run python -m judgment_assist.app.cli shogi --sfen "<sfen>" --engine "C:\\path\\to\\engine.exe"

# interactive REPL (sfen / move / go / show / reset / quit):
uv run python -m judgment_assist.app.cli shogi --engine "C:\\path\\to\\engine.exe"
```

`best_move` always tries an exact forced mate first (cheap, tsume-style checking
search), then asks the engine. Without an engine it still solves mates.

**In the GUI launcher.** `uv run python -m judgment_assist.app.launcher` → the
**Shogi** tab: paste an SFEN, optionally type moves, hit **Advise**. It prefills
the engine path + think-time from `config/shogi.json`, runs the think on a worker
thread (no freeze), and shows the board with the recommended move (forced-mate
line, or the engine's pick). Untick *Use USI engine* to get forced-mate-only
(Puzzle Shogi) with no binary.

---

## 5. The USI engine (verified: Fairy-Stockfish)

The advisor drives any engine that speaks **USI** (Universal Shogi Interface)
over stdin/stdout — `judgment_assist/shogi/engine.py::UsiEngine`. Even a modest
engine far outclasses Judgment's NPCs.

**Default engine: Fairy-Stockfish 14 (largeboard build).** Chosen because it's a
single self-contained `.exe`, speaks USI, and **defaults to the shogi variant
with no eval file** (classical eval) — no NNUE/ONNX download dance. Verified
end-to-end against `UsiEngine` (`usiok`/`readyok`/legal `bestmove`).

Setup (one-time):

1. Download the `*-largeboard` build from
   <https://github.com/fairy-stockfish/Fairy-Stockfish/releases> and drop the
   `.exe` in `judgment/engines/` (gitignored).
2. `cp config/shogi.example.json config/shogi.json` and set `engine` to its path.
   `config/shogi.json` is gitignored (machine-specific, like `regions.json`).

Engine resolution order: `--engine` flag → `$JUDGMENT_SHOGI_ENGINE` →
`config/shogi.json`. Optional `usi_options` in that file become `setoption`
commands at startup (e.g. `Threads`, `Hash`; `Skill_Level` -20..20 to weaken it).

Notes:
- Fairy-Stockfish's USI mode already selects the shogi variant, so no
  `UCI_Variant` option is required. Its move output is standard USI
  (`7g7f`, `G*5b`), compatible with `python-shogi`.
- Stronger but heavier alternative: **YaneuraOu** (needs a separate NNUE/ONNX
  eval). Drop its binary in `engines/`, point `config/shogi.json` at it — the
  driver is engine-agnostic.

---

## 6. Code map

| File | What |
|------|------|
| `shogi/board.py` | `ShogiState`: SFEN/USI, legal moves, check/mate (over `python-shogi`) |
| `shogi/mate.py` | pure-Python forced-mate (tsume) solver, no binary needed |
| `shogi/engine.py` | `UsiEngine` driver + `best_move` facade (mate-first, then engine) |
| `app/cli.py` (`shogi`) | manual advisor / REPL |

Tests: `tests/test_shogi_{board,mate,engine}.py` (the engine test uses a mock USI
process, `tests/_mock_usi.py`, so it runs with no real binary).

---

## 7. Vision — capturing the board

Capture reuses the shared layer (`capture/screen.py` + the Win32 window finder),
so it grabs the Judgment window exactly like poker/blackjack. What's shogi-specific
is in `vision/shogi_board.py`:

- **Geometry** — one board ROI `[left, top, w, h]` (the 9×9 grid) splits evenly
  into 81 cell rects. Files 9→1 left→right, ranks a→i top→bottom = SFEN order
  **when you (sente) sit at the bottom**; set `flip=True` if you play gote.
- **Occupancy** — a per-cell contrast heuristic ("is a piece here") for cropping
  pieces and as a sanity layer.
- **SFEN assembly** — `grid_to_sfen(grid, side, hands)` turns a 9×9 grid of piece
  codes into an SFEN the advisor accepts.
- **`ShogiBoardReader`** — frame → grid → SFEN, with a pluggable `recognizer`.

**One-time calibration** (needs a shogi frame on screen, ~2 min):

```
calibrate mark --game shogi --window Judgment        # drag a box around the 9x9 grid
#   or, on a saved screenshot (avoids the pause-on-focus-loss):
calibrate mark --game shogi --image data/shogi/frames/<ts>.png
```

This writes `shogi.board` into `config/regions.json`. Then the launcher's **Shogi
tab → Capture board** grabs the window, saves the frame to `data/shogi/frames/`
and the 81 cell crops to `data/shogi/cells/<ts>/`, and shows an occupancy map.

### Piece recognition (working)

`vision/shogi_pieces.py` reads *which* piece and *whose*. It's **template
matching, bootstrapped from the opening**: the opening layout is fixed, so a
capture of it auto-labels every piece — `build_templates()` crops each cell and
saves it as that piece's template. Owner is baked into the template (sente
upright, gote rotated 180°, and the two king glyphs 王/玉), so a match yields the
piece *and* its side with no rotation logic. `PieceRecognizer.classify` returns a
code, `""` (empty), or `None` (uncertain — unknown glyph or hand-obscured).
Validated: templates from one capture read a *different* capture back to the exact
opening SFEN.

**The hand cursor.** The player's pointer hand roams the board and covers pieces;
those cells read `None`. `StableBoardReader` keeps a running board where a `None`
cell **retains its prior value**, so the hand never wipes pieces — and successive
captures (as the hand moves) fill in whatever it was covering. Shogi changes one
move at a time, so the model stays correct.

**Flows:**

- **Per-capture** — Shogi tab selected, Judgment focused, press R4 (or the button)
  → board read into the SFEN field → best move shown.
- **Live read + overlay** — tick the *Live read + overlay* box: a floating box
  sits over the game and the board is re-read every ~1.2s, re-advising only when
  the position changes. It skips frames when the game isn't focused or is paused,
  so it never reads a stale screen. Untick (or quit) to stop.

*New game (reset)* clears the persistent board. *Promoted pieces* and
*pieces-in-hand* aren't in the opening — capture a mid-game board and
`add_templates()` extends the library.

**Readable advice.** The advice names the piece and marks the move on a labelled
board, e.g. `BEST MOVE: Silver 3i → 4h` with `F`/`T` markers and a legend
(CAPITALS = your pieces; files count right→left, ranks a top→i bottom). The
overlay shows the compact one-liner.

## 8. Roadmap (deferred)

1. **Promoted pieces + komadai** — `add_templates` from a mid-game capture for the
   promoted set; read the two hand trays so dropped-piece advice is exact.
2. **Explicit hand detector** — `None`+persistence already survives the hand;
   a skin/region detector (tuned on a frame with the hand over a piece) could mark
   obscured cells more eagerly. Wood is warm-toned, so it needs real data to tune.
3. **Puzzle Shogi UX** — feed the puzzle's piece set + move limit to the mate
   solver and show the full line.
