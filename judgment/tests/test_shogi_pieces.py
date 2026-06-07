import glob
import json
import os

import pytest

from judgment_assist.vision.shogi_board import StableBoardReader, grid_to_sfen
from judgment_assist.vision.shogi_pieces import (
    MANIFEST,
    OPENING_LAYOUT,
    _safe_name,
)


# ---------------------------------------------------------------- pure logic ---
def test_opening_layout_is_the_opening_position():
    from judgment_assist.shogi.board import START_SFEN
    assert grid_to_sfen(OPENING_LAYOUT) == START_SFEN
    pieces = sum(1 for row in OPENING_LAYOUT for v in row if v)
    assert pieces == 40


def test_safe_name_disambiguates_owner_and_promotion():
    assert _safe_name("P") == "b_P" and _safe_name("p") == "w_P"   # case-insensitive FS safe
    assert _safe_name("+R") == "prom_b_R" and _safe_name("+r") == "prom_w_R"
    assert _safe_name("K") != _safe_name("k")


class _StubReader:
    """A ShogiBoardReader stand-in returning scripted raw grids (incl. None)."""
    def __init__(self, grids):
        self.grids, self.i = grids, 0

    def classify_grid(self, frame):
        g = [row[:] for row in self.grids[min(self.i, len(self.grids) - 1)]]
        self.i += 1
        return g


def test_stable_board_keeps_obscured_cells_and_applies_confident_reads():
    g1 = [[""] * 9 for _ in range(9)]; g1[8][0] = "P"; g1[0][0] = None  # hand over (0,0)
    g2 = [[""] * 9 for _ in range(9)]; g2[8][0] = None; g2[0][0] = "l"  # hand now over (8,0)
    sb = StableBoardReader(_StubReader([g1, g2]))

    sb.update(None)
    assert sb.grid[8][0] == "P"          # confident piece applied
    assert sb.grid[0][0] == ""           # None -> kept prior (empty)

    sb.update(None)
    assert sb.grid[8][0] == "P"          # None -> kept the piece (hand didn't wipe it)
    assert sb.grid[0][0] == "l"          # confident update where the hand left


def test_stable_board_obscured_count_and_reset():
    g = [[""] * 9 for _ in range(9)]; g[0][0] = None; g[1][1] = None; g[8][8] = "K"
    sb = StableBoardReader(_StubReader([g]))
    assert sb.obscured(None) == 2
    sb.update(None); assert sb.grid[8][8] == "K"
    sb.reset(); assert all(v == "" for row in sb.grid for v in row)


# ----------------------------------------------------- recognizer (synthetic) ---
def test_save_template_is_additive_not_clobbering(tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from judgment_assist.vision.shogi_pieces import (
        MANIFEST, PieceRecognizer, save_template_from_crop)
    a = np.zeros((90, 80, 3), np.uint8); a[20:70, 30:50] = 255
    b = np.zeros((90, 80, 3), np.uint8); b[10:80, 18:62] = 200
    save_template_from_crop(a, "+r", str(tmp_path))
    save_template_from_crop(b, "+r", str(tmp_path))      # must ADD, not overwrite
    man = json.load(open(tmp_path / MANIFEST, encoding="utf-8"))
    assert sum(1 for c in man.values() if c == "+r") == 2
    rec = PieceRecognizer(str(tmp_path))
    assert len(rec.templates["+r"]) == 2                  # both examples loaded


def test_recognizer_classifies_synthetic_templates(tmp_path):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from judgment_assist.vision.shogi_pieces import PieceRecognizer

    bar_v = np.zeros((90, 80, 3), np.uint8); bar_v[20:70, 34:46] = 255   # vertical bar
    bar_h = np.zeros((90, 80, 3), np.uint8); bar_h[40:52, 12:68] = 255   # horizontal bar
    cv2.imwrite(str(tmp_path / "b_P.png"), bar_v)
    cv2.imwrite(str(tmp_path / "w_P.png"), bar_h)
    json.dump({"b_P.png": "P", "w_P.png": "p"}, open(tmp_path / MANIFEST, "w"))

    rec = PieceRecognizer(str(tmp_path), threshold=0.3, occ_threshold=5.0)
    assert rec.classify(bar_v) == "P"
    assert rec.classify(bar_h) == "p"
    assert rec.classify(np.full((90, 80, 3), 120, np.uint8)) == ""   # flat -> empty


# --------------------------------------------------- real-frame pipeline test ---
def test_recognizer_reads_a_legal_board_from_real_frames():
    """End-to-end on captured frames (jonaS's machine): build templates from one,
    read another, and confirm it yields a legal board python-shogi accepts."""
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    import shogi
    from judgment_assist.app.launcher import ROOT
    from judgment_assist.vision.shogi_board import ShogiBoardReader
    from judgment_assist.vision.shogi_pieces import build_templates, PieceRecognizer

    frames = sorted(glob.glob(str(ROOT / "data" / "shogi" / "frames" / "*.png")))
    reg = ROOT / "config" / "regions.json"
    if len(frames) < 2 or not reg.exists():
        pytest.skip("need >=2 captured frames + a calibrated regions.json")
    board = (json.load(open(reg, encoding="utf-8")).get("shogi") or {}).get("board")
    if not board or list(board) == [0, 0, 0, 0]:
        pytest.skip("shogi.board not calibrated")

    built = build_templates(cv2.imread(frames[-1]), board, str(tmp := ROOT / "data" / "shogi" / "_test_tpl"))
    assert built                                  # auto-labeled some pieces
    rec = PieceRecognizer(str(tmp))
    sfen = ShogiBoardReader(board, recognizer=rec).read_sfen(cv2.imread(frames[0]))
    shogi.Board(sfen)                             # raises if the read board is illegal
    assert sum(c.isalpha() for c in sfen.split()[0]) >= 20   # a populated board
