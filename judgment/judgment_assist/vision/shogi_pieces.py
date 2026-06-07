"""Shogi piece recognition — template matching, bootstrapped from the opening.

The opening position is fixed, so a capture of it auto-labels every piece: we crop
each occupied cell and save it as the template for that piece. Owner is baked into
the template — **sente (your) pieces are upright, gote pieces are rotated 180°**,
and the two kings even use different glyphs (王 vs 玉) — so matching a crop against
the on-screen templates yields both the piece *and* whose it is, no rotation logic.

:class:`PieceRecognizer.classify` returns:

- ``""``    the cell is empty,
- a code    (``P l +R`` …) the best-matching piece, when confident,
- ``None``  uncertain — an unknown glyph (e.g. a promoted piece with no template
            yet) **or the player's hand cursor obscuring the cell**. Callers keep
            the cell's previous value (see :class:`vision.shogi_board`'s stateful
            reader) so the roaming hand never wipes the board.

Promoted pieces and pieces-in-hand aren't in the opening; capture a mid-game board
and call :func:`add_templates` to extend the library.
"""
from __future__ import annotations

import json
import os

try:
    import cv2
    import numpy as np
    _HAVE_DEPS = True
except Exception:  # pragma: no cover - only without cv2/numpy
    _HAVE_DEPS = False

# The fixed opening layout, in SFEN order (row 0 = rank a = gote's back rank at
# the TOP of the screen; col 0 = file 9 = leftmost). Lower = gote, upper = sente.
_E = ""
OPENING_LAYOUT = [
    list("lnsgkgsnl"),
    [_E, "r", _E, _E, _E, _E, _E, "b", _E],
    list("ppppppppp"),
    [_E] * 9, [_E] * 9, [_E] * 9,
    list("PPPPPPPPP"),
    [_E, "B", _E, _E, _E, _E, _E, "R", _E],
    list("LNSGKGSNL"),
]

CANON_W, CANON_H = 64, 72          # templates/crops normalised to this for matching
MANIFEST = "manifest.json"          # filename -> piece code (avoids '+'/case in names)


def _canon(crop):
    """Centre-crop (drop the grid border), grayscale, resize to canonical size,
    float32. The shared representation for templates and query crops."""
    h, w = crop.shape[:2]
    m = crop[int(h * 0.10):int(h * 0.90), int(w * 0.10):int(w * 0.90)]
    if m.size == 0:
        m = crop
    g = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY) if m.ndim == 3 else m
    return cv2.resize(g, (CANON_W, CANON_H)).astype("float32")


def _ncc(a, b):
    """Normalised cross-correlation of two equal-size canonical images (-1..1)."""
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])


def _safe_name(code):
    """Piece code -> filename stem. '+R' -> 'prom_R', 'p' -> 'w_p', 'P' -> 'b_P'
    (case-insensitive filesystems would otherwise collide P/p)."""
    if code.startswith("+"):
        base = code[1:]
        return ("prom_b_" if base.isupper() else "prom_w_") + base.upper()
    return ("b_" if code.isupper() else "w_") + code.upper()


# ------------------------------------------------------------- build library ---
def build_templates(frame, board_roi, out_dir, layout=OPENING_LAYOUT):
    """Crop every known piece in ``layout`` from ``frame`` and write it as that
    piece's template (+ a manifest). Returns ``{code: path}``.

    Use on an **opening** capture (the default layout). Each occupied cell's crop
    becomes the canonical template for its piece code."""
    from .shogi_board import cell_rects
    if not _HAVE_DEPS:
        raise RuntimeError("shogi piece templates need: pip install opencv-python numpy")
    os.makedirs(out_dir, exist_ok=True)
    rects = cell_rects(board_roi)
    manifest, written = {}, {}
    for r in range(9):
        for c in range(9):
            code = layout[r][c]
            if not code:
                continue
            l, t, w, h = rects[r][c]
            stem = _safe_name(code) + ".png"
            cv2.imwrite(os.path.join(out_dir, stem), frame[t:t + h, l:l + w])
            manifest[stem] = code
            written[code] = os.path.join(out_dir, stem)
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return written


def save_template_from_crop(crop_img, code, out_dir):
    """Label a cell crop: save ``crop_img`` as the template for ``code`` (e.g.
    ``"+r"``), merging the manifest. This is the manual-labelling entry point —
    the human assigns the piece, so it's authoritative. Returns ``code``."""
    if not _HAVE_DEPS:
        raise RuntimeError("shogi templates need: pip install opencv-python numpy")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, MANIFEST)
    manifest = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    stem = _safe_name(code) + ".png"
    cv2.imwrite(os.path.join(out_dir, stem), crop_img)
    manifest[stem] = code
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return code


def remove_template(code, out_dir):
    """Delete the template for ``code`` (undo a mislabel). Returns True if removed."""
    path = os.path.join(out_dir, MANIFEST)
    if not os.path.exists(path):
        return False
    manifest = json.load(open(path, encoding="utf-8"))
    stem = next((s for s, cd in manifest.items() if cd == code), None)
    if stem is None:
        return False
    manifest.pop(stem)
    fp = os.path.join(out_dir, stem)
    if os.path.exists(fp):
        os.remove(fp)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return True


def add_templates(frame, board_roi, layout, out_dir):
    """Add/overwrite templates for the occupied cells in a (partial) ``layout`` —
    e.g. a mid-game capture to pick up promoted pieces. Merges into the manifest."""
    if not _HAVE_DEPS:
        raise RuntimeError("shogi piece templates need: pip install opencv-python numpy")
    from .shogi_board import cell_rects
    path = os.path.join(out_dir, MANIFEST)
    manifest = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    rects = cell_rects(board_roi)
    added = []
    for r in range(9):
        for c in range(9):
            code = layout[r][c]
            if not code:
                continue
            l, t, w, h = rects[r][c]
            stem = _safe_name(code) + ".png"
            cv2.imwrite(os.path.join(out_dir, stem), frame[t:t + h, l:l + w])
            manifest[stem] = code
            added.append(code)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return added


# ----------------------------------------------------------------- recognizer ---
class PieceRecognizer:
    """Classify a cell crop against the template library.

    ``threshold`` is the minimum NCC to accept a match; below it (or an empty-ish
    cell that still has clutter, e.g. the hand) ``classify`` returns ``None`` so
    the caller keeps the prior value. ``occ_threshold`` gates obviously-empty cells
    to ``""`` quickly. Both are tunable against real captures."""

    def __init__(self, templates_dir, threshold=0.40, occ_threshold=16.0):
        if not _HAVE_DEPS:
            raise RuntimeError("shogi recognition needs: pip install opencv-python numpy")
        self.threshold = threshold
        self.occ_threshold = occ_threshold
        self.templates = {}                       # code -> canonical float32
        path = os.path.join(templates_dir, MANIFEST)
        if not os.path.exists(path):
            raise RuntimeError(f"no template manifest in {templates_dir} "
                               f"(build it from an opening capture first)")
        for stem, code in json.load(open(path, encoding="utf-8")).items():
            img = cv2.imread(os.path.join(templates_dir, stem))
            if img is not None:
                self.templates[code] = _canon(img)

    def scores(self, crop):
        """``{code: ncc}`` for every template (diagnostics / threshold tuning)."""
        c = _canon(crop)
        return {code: _ncc(c, t) for code, t in self.templates.items()}

    def classify(self, crop):
        """``""`` empty, a piece code when confident, or ``None`` when uncertain
        (unknown glyph or hand-obscured)."""
        return self.classify_conf(crop)[0]

    def classify_conf(self, crop):
        """``(code, score)``: ``code`` is ``""`` (empty), a piece when the best NCC
        clears ``threshold``, else ``None``; ``score`` is that best NCC. The score
        lets callers flag *force-matched* cells (a promoted piece with no template
        matches an unpromoted one weakly) for review, not just ``None`` ones."""
        from .shogi_board import cell_score
        if cell_score(crop) < self.occ_threshold:
            return "", 1.0
        best_code, best = None, -1.0
        c = _canon(crop)
        for code, t in self.templates.items():
            s = _ncc(c, t)
            if s > best:
                best, best_code = s, code
        return (best_code if best >= self.threshold else None), best
