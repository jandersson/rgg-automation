import shogi
import pytest

from judgment_assist.shogi.mate import find_mate, mate_in

MATE_IN_1 = "4k4/9/4G4/9/9/9/9/9/4K4 b G 1"  # Black: drop Gold 5b == mate


def _play(sfen, pv):
    b = shogi.Board(sfen)
    for usi in pv:
        b.push(shogi.Move.from_usi(usi))
    return b


def test_mate_in_one_found():
    b = shogi.Board(MATE_IN_1)
    assert not b.is_check()              # legal: opponent not already in check
    pv = find_mate(b, 1)
    assert pv == ["G*5b"]
    assert mate_in(pv) == 1


def test_found_pv_actually_checkmates():
    pv = find_mate(shogi.Board(MATE_IN_1), 1)
    assert _play(MATE_IN_1, pv).is_checkmate()


def test_deeper_budget_still_returns_the_mate():
    # extra budget must not hide an available mate
    assert find_mate(shogi.Board(MATE_IN_1), 5) == ["G*5b"]


def test_require_check_filters_to_checking_first_move():
    pv = find_mate(shogi.Board(MATE_IN_1), 1, require_check=True)
    b = _play(MATE_IN_1, pv[:1])
    assert b.is_check()                  # the attacker's move gives check


def test_no_forced_mate_returns_none():
    # nothing is forced from the opening; exercises the _attack/_defend recursion
    assert find_mate(shogi.Board(), 3, require_check=True) is None
    assert find_mate(shogi.Board(), 2, require_check=False) is None


def test_max_moves_validated():
    with pytest.raises(ValueError):
        find_mate(shogi.Board(), 0)


def test_find_mate_respects_node_budget():
    # a deep no-check-required search would be enormous; a tiny budget must make it
    # give up (return None) rather than hang.
    assert find_mate(shogi.Board(), 7, require_check=False, max_nodes=50) is None
    # the budget never hides an immediate mate
    assert find_mate(shogi.Board(MATE_IN_1), 1, max_nodes=50) == ["G*5b"]
