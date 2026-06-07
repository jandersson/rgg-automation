import pytest

from judgment_assist.vision.shogi_board import (
    ShogiBoardReader,
    cell_rects,
    grid_to_sfen,
    occupancy_grid,
    split_board,
)
from judgment_assist.shogi.board import START_SFEN


# ------------------------------------------------------------------ geometry ---
def test_cell_rects_tile_the_roi_exactly():
    rects = cell_rects([0, 0, 90, 90])
    assert len(rects) == 9 and all(len(r) == 9 for r in rects)
    assert rects[0][0] == [0, 0, 10, 10]
    assert rects[8][8] == [80, 80, 10, 10]
    # right/bottom edge of the last cell reaches the ROI edge (no gap)
    l, t, w, h = rects[8][8]
    assert l + w == 90 and t + h == 90


def test_cell_rects_handle_nondivisible_size():
    rects = cell_rects([5, 7, 100, 100])     # 100/9 is not integer
    # columns/rows still span the full ROI without overlap or gap
    assert rects[0][0][0] == 5 and rects[8][8][0] + rects[8][8][2] == 105
    widths = [rects[0][c][2] for c in range(9)]
    assert sum(widths) == 100


# ---------------------------------------------------------------------- SFEN ---
def _opening_grid():
    e = ""
    return [
        list("lnsgkgsnl"),
        [e, "r", e, e, e, e, e, "b", e],
        list("ppppppppp"),
        [e] * 9, [e] * 9, [e] * 9,
        list("PPPPPPPPP"),
        [e, "B", e, e, e, e, e, "R", e],
        list("LNSGKGSNL"),
    ]


def test_grid_to_sfen_matches_opening_position():
    assert grid_to_sfen(_opening_grid(), side="b", hands=None) == START_SFEN


def test_grid_to_sfen_promoted_and_hands():
    grid = [[""] * 9 for _ in range(9)]
    grid[2][4] = "+P"            # a tokin
    grid[6][4] = "k"
    sfen = grid_to_sfen(grid, side="w", hands={"P": 2, "b": 1})
    assert sfen.split()[0] == "9/9/4+P4/9/9/9/4k4/9/9"
    assert sfen.split()[1] == "w"
    assert sfen.split()[2] == "2Pb"      # Black caps first, count prefix when >1


def test_grid_to_sfen_rejects_unrecognized_and_unpromotable():
    bad = [[""] * 9 for _ in range(9)]
    bad[0][0] = "?"              # occupancy-only marker is not a real piece
    with pytest.raises(ValueError):
        grid_to_sfen(bad)
    bad[0][0] = "+K"            # kings can't promote
    with pytest.raises(ValueError):
        grid_to_sfen(bad)


def test_grid_to_sfen_requires_9x9():
    with pytest.raises(ValueError):
        grid_to_sfen([[""] * 9 for _ in range(8)])


# --------------------------------------------------------- occupancy / read ---
def _board_frame():
    np = pytest.importorskip("numpy")
    # 90×90 "board": flat wood everywhere, one high-contrast piece at cell (0,0)
    frame = np.full((90, 90, 3), 120, np.uint8)
    frame[1:9, 1:5] = 255            # bright mark inside the top-left cell centre
    frame[1:9, 5:9] = 0
    return frame


def test_split_board_shapes():
    pytest.importorskip("numpy")
    crops = split_board(_board_frame(), [0, 0, 90, 90])
    assert len(crops) == 9 and len(crops[0]) == 9
    assert crops[0][0].shape[:2] == (10, 10)


def test_occupancy_detects_the_single_piece():
    pytest.importorskip("numpy")
    occ = occupancy_grid(_board_frame(), [0, 0, 90, 90])
    assert occ[0][0] is True
    # every other cell is flat wood -> empty
    assert sum(v for row in occ for v in row) == 1


def test_reader_without_recognizer_marks_occupied_cells():
    pytest.importorskip("numpy")
    reader = ShogiBoardReader([0, 0, 90, 90])
    grid = reader.read_grid(_board_frame())
    assert grid[0][0] == "?" and grid[1][1] == ""
    # '?' is not a real piece, so a SFEN read must refuse without a recognizer
    with pytest.raises(ValueError):
        reader.read_sfen(_board_frame())


def test_reader_flip_swaps_corners():
    pytest.importorskip("numpy")
    reader = ShogiBoardReader([0, 0, 90, 90], flip=True)
    grid = reader.read_grid(_board_frame())
    assert grid[8][8] == "?"        # top-left piece maps to bottom-right when flipped


def test_reader_with_recognizer_builds_sfen():
    pytest.importorskip("numpy")

    class _Rec:
        # trivial stand-in: report a sente pawn only in the top-left cell
        def __init__(self):
            self.calls = 0

        def classify(self, crop):
            self.calls += 1
            return "P" if self.calls == 1 else ""

    reader = ShogiBoardReader([0, 0, 90, 90], recognizer=_Rec())
    sfen = reader.read_sfen(_board_frame())
    assert sfen.startswith("P8/9/")


def test_save_cells_writes_81_crops(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    import os
    from judgment_assist.vision.shogi_board import save_cells
    paths = save_cells(_board_frame(), [0, 0, 90, 90], str(tmp_path))
    assert len(paths) == 81
    assert os.path.exists(tmp_path / "r0c0.png") and os.path.exists(tmp_path / "r8c8.png")


def test_uncertain_cells_flags_occupied_but_unread():
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")

    from judgment_assist.vision.shogi_board import cell_score

    class _NoneRec:                       # never recognizes -> occupied cells are "unread"
        def classify_conf(self, crop):
            return ("", 1.0) if cell_score(crop) < 16 else (None, 0.0)

    reader = ShogiBoardReader([0, 0, 90, 90], recognizer=_NoneRec())
    # _board_frame has one occupied cell (0,0); the rest are flat wood
    assert reader.uncertain_cells(_board_frame()) == [(0, 0)]


def test_uncertain_cells_flags_weak_force_match(tmp_path):
    pytest.importorskip("numpy")

    class _WeakRec:                       # returns a code but at low confidence
        def classify_conf(self, crop):
            from judgment_assist.vision.shogi_board import cell_score
            return ("", 1.0) if cell_score(crop) < 16 else ("l", 0.45)

    reader = ShogiBoardReader([0, 0, 90, 90], recognizer=_WeakRec())
    # the one occupied cell force-matches 'l' at 0.45 (< 0.6) -> still flagged for review
    assert reader.uncertain_cells(_board_frame()) == [(0, 0)]


def test_save_review_cells_writes_named_crops(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    import os
    from judgment_assist.vision.shogi_board import save_review_cells
    paths = save_review_cells(_board_frame(), [0, 0, 90, 90], [(0, 0), (8, 8)],
                              str(tmp_path), "live_X")
    assert len(paths) == 2
    assert os.path.exists(tmp_path / "live_X_r0c0.png")
    assert os.path.exists(tmp_path / "live_X_r8c8.png")
