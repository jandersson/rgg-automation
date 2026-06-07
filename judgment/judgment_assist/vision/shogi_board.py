"""Shogi board vision — turn a screen grab into a board grid / SFEN.

The capture layer (``capture/screen.py`` + window finder) is shared with the other
games; what's shogi-specific lives here:

1. **Geometry** — a single board ROI ``[left, top, w, h]`` (the 9×9 playing grid)
   splits evenly into 81 cell rects. Files run 9→1 left→right, ranks a→i
   top→bottom, which is SFEN order **when sente (you) sits at the bottom** — the
   usual case in Judgment. Set ``flip=True`` if you're playing gote.
2. **Occupancy** — a cheap heuristic (per-cell contrast) for "is there a piece
   here", used to crop pieces for the template library and as a sanity layer.
3. **SFEN assembly** — a 9×9 grid of piece codes → an SFEN string the advisor and
   ``python-shogi`` accept.

Piece **recognition** (which piece, whose) is the remaining phase: it needs a
template library built from real captured cells, so :class:`ShogiBoardReader`
takes a pluggable ``recognizer`` and, without one, reports occupancy only.

Codes use SFEN letters: upper = Black/sente, lower = White/gote, ``+`` = promoted
(``P L N S G B R K`` / ``k``). Empty cell = ``""``.
"""
from __future__ import annotations

try:
    import numpy as np
    _HAVE_NP = True
except Exception:  # pragma: no cover - only without numpy
    _HAVE_NP = False

N = 9  # board is 9×9

# Standard SFEN hand ordering (most valuable first), used when serialising hands.
_HAND_ORDER = "RBGSNLP"


# --------------------------------------------------------------- geometry ---
def cell_rects(board_roi):
    """Split a board ROI ``[l, t, w, h]`` into a 9×9 list (rows top→bottom,
    cols left→right) of ``[l, t, w, h]`` cell rects by even division.

    Uses rounded fractional boundaries so the cells tile the ROI exactly (no
    cumulative gap from a truncated integer cell width)."""
    l, t, w, h = board_roi
    xs = [round(l + w * i / N) for i in range(N + 1)]
    ys = [round(t + h * j / N) for j in range(N + 1)]
    rects = []
    for r in range(N):
        row = []
        for c in range(N):
            row.append([xs[c], ys[r], xs[c + 1] - xs[c], ys[r + 1] - ys[r]])
        rects.append(row)
    return rects


def split_board(frame, board_roi):
    """Return a 9×9 grid of cell crops (numpy views) from ``frame``."""
    out = []
    for row in cell_rects(board_roi):
        crops = []
        for (l, t, w, h) in row:
            crops.append(frame[t:t + h, l:l + w])
        out.append(crops)
    return out


# --------------------------------------------------------------- occupancy ---
def cell_score(crop):
    """Contrast score for a cell crop: stddev of its grayscale. A piece (kanji on
    a light pentagon) is high-contrast; bare wood is comparatively flat."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return 0.0
    g = crop.astype("float32")
    if g.ndim == 3:
        g = g.mean(axis=2)
    # ignore the cell's outer border (grid lines) — sample the centre
    h, w = g.shape
    m = slice(int(h * 0.18), int(h * 0.82)), slice(int(w * 0.18), int(w * 0.82))
    centre = g[m] if g[m].size else g
    return float(centre.std())


def cell_occupied(crop, threshold=18.0):
    """Heuristic: is a piece sitting on this cell? ``threshold`` is on
    :func:`cell_score` (grayscale stddev). Tune against real captures."""
    return cell_score(crop) >= threshold


def occupancy_grid(frame, board_roi, threshold=18.0):
    """9×9 list of bools — which cells look occupied."""
    return [[cell_occupied(c, threshold) for c in row]
            for row in split_board(frame, board_roi)]


# --------------------------------------------------------------- SFEN ---
def _serialise_hands(hands):
    """``{'P': 2, 'p': 1}`` → ``'2Pp'`` in SFEN order (Black caps first). ``None``
    or empty → ``'-'``. Accepts a ready string and returns it unchanged."""
    if hands is None or hands == "":
        return "-"
    if isinstance(hands, str):
        return hands
    out = []
    for letters in (_HAND_ORDER, _HAND_ORDER.lower()):
        for p in letters:
            n = hands.get(p, 0)
            if n:
                out.append((str(n) if n > 1 else "") + p)
    return "".join(out) or "-"


def grid_to_sfen(grid, side="b", hands=None, move=1):
    """Assemble an SFEN from a 9×9 ``grid`` of piece codes.

    ``grid[0]`` is the top rank (rank *a*), ``grid[r][0]`` the leftmost file
    (file 9) — i.e. canonical SFEN order. ``side`` is ``'b'`` (Black/sente) or
    ``'w'``. ``hands`` is a count dict (see :func:`_serialise_hands`) or string.

    Raises ``ValueError`` on a malformed grid or an unrecognised code (e.g. the
    ``'?'`` an occupancy-only read leaves behind — a reminder that you need a
    recognizer for a real SFEN)."""
    if len(grid) != N or any(len(row) != N for row in grid):
        raise ValueError("grid must be 9×9")
    rows = []
    for r, row in enumerate(grid):
        s, empty = "", 0
        for code in row:
            if code in ("", None):
                empty += 1
                continue
            if not _valid_code(code):
                raise ValueError(f"bad piece code {code!r} at rank {'abcdefghi'[r]}")
            if empty:
                s += str(empty)
                empty = 0
            s += code
        if empty:
            s += str(empty)
        rows.append(s)
    return f"{'/'.join(rows)} {side} {_serialise_hands(hands)} {move}"


_PIECES = set("PLNSGBRK")


def _valid_code(code):
    body = code[1:] if code.startswith("+") else code
    return len(body) == 1 and body.upper() in _PIECES and not (
        code.startswith("+") and body.upper() == "K")  # kings don't promote


# --------------------------------------------------------------- reader ---
class ShogiBoardReader:
    """Read a board from a captured frame.

    ``recognizer.classify(crop)`` should return a piece code (``''`` for empty).
    Without a recognizer, :meth:`read_grid` reports occupancy as ``'?'`` so you
    can still capture and inspect cells, but :meth:`read_sfen` will refuse
    (``'?'`` isn't a real piece) — that's the signal the template library /
    recognizer is the next step.
    """

    def __init__(self, board_roi, recognizer=None, flip=False, threshold=18.0):
        self.board_roi = board_roi
        self.recognizer = recognizer
        self.flip = flip
        self.threshold = threshold

    def cells(self):
        return cell_rects(self.board_roi)

    def split(self, frame):
        return split_board(frame, self.board_roi)

    def read_grid(self, frame):
        grid = []
        for row in self.split(frame):
            out = []
            for crop in row:
                if self.recognizer is not None:
                    out.append(self.recognizer.classify(crop) or "")
                else:
                    out.append("?" if cell_occupied(crop, self.threshold) else "")
            grid.append(out)
        if self.flip:
            grid = [list(reversed(r)) for r in reversed(grid)]
        return grid

    def read_sfen(self, frame, side="b", hands=None, move=1):
        return grid_to_sfen(self.read_grid(frame), side=side, hands=hands, move=move)


# --------------------------------------------------------------- capture I/O ---
def save_cells(frame, board_roi, out_dir):
    """Split ``frame`` by ``board_roi`` and write all 81 cell crops to ``out_dir``
    as ``r{row}c{col}.png`` (row/col 0-8, top-left origin). Returns the paths.

    This is the bootstrap for piece recognition: capture a real board, then label
    these crops into a template library."""
    import os

    import cv2
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    rects = cell_rects(board_roi)
    for r in range(N):
        for c in range(N):
            l, t, w, h = rects[r][c]
            p = os.path.join(out_dir, f"r{r}c{c}.png")
            cv2.imwrite(p, frame[t:t + h, l:l + w])
            paths.append(p)
    return paths
