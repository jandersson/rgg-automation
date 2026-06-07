import pytest

from judgment_assist.shogi.board import START_SFEN, ShogiState


def test_start_position_basics():
    s = ShogiState()
    assert s.black_to_move
    assert len(s.legal_moves()) == 30      # 30 legal opening moves in shogi
    assert not s.is_check() and not s.is_checkmate()
    assert s.sfen == START_SFEN


def test_push_usi_advances_turn():
    s = ShogiState()
    s.push_usi("7g7f")
    assert not s.black_to_move               # White to move now
    assert "7g7f" not in s.legal_moves()     # that pawn already moved


def test_illegal_and_garbled_moves_raise():
    s = ShogiState()
    with pytest.raises(ValueError):
        s.push_usi("5e5d")                   # nothing on 5e at the start
    with pytest.raises(ValueError):
        s.push_usi("not-a-move")


def test_sfen_roundtrip_and_copy_isolation():
    s = ShogiState("4k4/9/4G4/9/9/9/9/9/4K4 b G 1")
    twin = s.copy()
    s.push_usi("G*5b")
    assert twin.sfen == "4k4/9/4G4/9/9/9/9/9/4K4 b G 1"   # copy untouched
    assert s.is_checkmate()


def test_render_flags_checkmate():
    s = ShogiState("4k4/9/4G4/9/9/9/9/9/4K4 b G 1")
    s.push_usi("G*5b")
    assert "CHECKMATE" in s.render()
