import os
import sys

from judgment_assist.shogi.board import ShogiState
from judgment_assist.shogi.engine import UsiEngine, best_move

MOCK = [sys.executable, os.path.join(os.path.dirname(__file__), "_mock_usi.py")]
MATE_IN_1 = "4k4/9/4G4/9/9/9/9/9/4K4 b G 1"


def test_usi_driver_roundtrip_with_mock_engine():
    eng = UsiEngine(MOCK).start()
    try:
        assert eng.best_move(ShogiState().sfen, movetime_ms=10) == "7g7f"
    finally:
        eng.close()


def test_best_move_prefers_forced_mate_over_engine():
    # Even with an engine wired up, an exact forced mate wins.
    eng = UsiEngine(MOCK).start()
    try:
        out = best_move(ShogiState(MATE_IN_1), engine=eng, mate_moves=3)
        assert out["source"] == "mate"
        assert out["move"] == "G*5b"
        assert out["mate_in"] == 1
    finally:
        eng.close()


def test_best_move_falls_back_to_engine_when_no_mate():
    eng = UsiEngine(MOCK).start()
    try:
        out = best_move(ShogiState(), engine=eng, mate_moves=3)
        assert out["source"] == "engine"
        assert out["move"] == "7g7f"
    finally:
        eng.close()


def test_best_move_without_engine_reports_none():
    out = best_move(ShogiState(), engine=None, mate_moves=3)
    assert out["source"] == "none"
    assert out["move"] is None
