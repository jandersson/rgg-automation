"""Human-readable advice rendering (no display, no engine)."""
from judgment_assist.app.shogi_tab import (
    board_is_playable,
    describe_move,
    format_overlay_line,
    format_result,
    render_board,
)
from judgment_assist.shogi.board import START_SFEN


def test_board_is_playable_guards_against_non_boards():
    assert board_is_playable(START_SFEN)                       # real position
    assert not board_is_playable("9/9/9/9/9/9/9/9/9 b - 1")    # no kings (open world/garbage)
    assert not board_is_playable("4k4/9/9/9/9/9/9/9/9 b - 1")  # only one king
    assert board_is_playable("4k4/9/9/9/9/9/9/9/4K4 b - 1")    # both kings -> ok

DROP_POS = "4k4/9/9/9/9/9/9/9/4K4 b G 1"


def test_describe_move_names_the_piece():
    assert describe_move(START_SFEN, "7g7f").startswith("Pawn")
    assert describe_move(START_SFEN, "3i4h").startswith("Silver")   # right silver
    assert "3i" in describe_move(START_SFEN, "3i4h")
    assert "4h" in describe_move(START_SFEN, "3i4h")


def test_describe_move_drop_and_promote():
    assert describe_move(DROP_POS, "G*5b") == "drop Gold → 5b"
    assert "(promote)" in describe_move("9/9/9/9/9/9/6R2/9/4K2k1 b - 1", "3g3b+")


def test_render_board_has_labels_and_markers():
    out = render_board(START_SFEN, "7g7f")
    assert "9 8 7 6 5 4 3 2 1" in out          # file header
    assert out.splitlines()[1].startswith(" a")   # rank letters
    assert "F" in out and "T" in out           # from/to marked


def test_render_board_marks_correct_squares():
    # 7g7f: file 7 -> col 9-7=2; ranks g (row6) and f (row5)
    lines = render_board(START_SFEN, "7g7f").splitlines()
    # line 0 is the header; rank g is the 7th data row -> lines[1+6]
    g_row = lines[1 + 6].split()[1:]           # drop the rank-letter label
    f_row = lines[1 + 5].split()[1:]
    assert g_row[2] == "F" and f_row[2] == "T"


def test_format_result_is_readable():
    out = format_result(START_SFEN, {"move": "7g7f", "source": "engine"})
    assert "BEST MOVE:" in out and "Pawn" in out
    assert "CAPITALS = your pieces" in out
    assert "9 8 7 6 5 4 3 2 1" in out


def test_format_overlay_line_compact():
    assert format_overlay_line(START_SFEN, {"move": "7g7f", "source": "engine"}).startswith("BEST:")
    mate = format_overlay_line(DROP_POS, {"move": "G*5b", "source": "mate",
                                          "mate_in": 1, "pv": ["G*5b"]})
    assert mate.startswith("MATE in 1:")
    assert format_overlay_line(START_SFEN, {"move": None, "source": "none",
                                            "note": "no advice"}) == "no advice"
