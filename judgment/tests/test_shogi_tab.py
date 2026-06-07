"""Pure-logic tests for the launcher's Shogi tab (no display, no engine)."""
from judgment_assist.app.shogi_tab import (
    DEFAULT_MOVETIME,
    build_state,
    format_advice,
    load_engine_config,
)
from judgment_assist.shogi.board import START_SFEN
from judgment_assist.shogi.engine import best_move

MATE_IN_1 = "4k4/9/4G4/9/9/9/9/9/4K4 b G 1"


def test_build_state_blank_is_opening():
    state, err = build_state("", "")
    assert err is None and state.sfen == START_SFEN


def test_build_state_applies_moves():
    state, err = build_state("", "7g7f 3c3d")
    assert err is None
    assert state.black_to_move        # two plies played -> back to Black


def test_build_state_reports_bad_sfen_and_illegal_move():
    state, err = build_state("not a sfen", "")
    assert state is None and "SFEN" in err
    state, err = build_state("", "5e5d")           # nothing on 5e at the opening
    assert state is None and "illegal" in err


def test_format_advice_mate_line():
    state, _ = build_state(MATE_IN_1, "")
    out = best_move(state, engine=None)            # mate solver only, no engine
    text = format_advice(out)
    assert "G*5b" in text and "forced mate in 1" in text


def test_format_advice_no_engine_note():
    state, _ = build_state("", "")
    out = best_move(state, engine=None)            # opening, no mate, no engine
    assert format_advice(out) == out["note"]


def test_load_engine_config_missing_is_safe(tmp_path):
    # tmp_path has no config/shogi.json -> blanks, no raise
    path, opts, movetime = load_engine_config(tmp_path)
    assert path == "" and opts == {} and movetime == DEFAULT_MOVETIME
