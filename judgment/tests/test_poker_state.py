"""Label-free poker game-state reading (street + card-present)."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from judgment_assist.vision import poker as P

CFG = {"corner": [70, 105],
       "hole": [[652, 625], [984, 625]],
       "board": [[296, 298], [562, 298], [838, 298], [1128, 298], [1410, 298]]}


def _felt(): return np.full((1080, 1920, 3), (70, 120, 40), np.uint8)


def _deal(frame, n):
    """Paint n white 'cards' at the first n board slots (+ both hole slots)."""
    for x, y in CFG["board"][:n] + CFG["hole"]:
        frame[y:y + 200, x - 4:x + 180] = (245, 245, 245)
    return frame


def test_card_present_vs_empty():
    f = _deal(_felt(), 3)
    cw, ch = CFG["corner"]
    bx, by = CFG["board"][0]
    assert P.card_present(f[by:by + ch, bx:bx + cw]) is True          # dealt slot
    ex, ey = CFG["board"][4]
    assert P.card_present(f[ey:ey + ch, ex:ex + cw]) is False          # empty slot (felt)


@pytest.mark.parametrize("n,name", [(0, "preflop"), (3, "flop"), (4, "turn"), (5, "river")])
def test_street_from_board_count(n, name):
    assert P.board_count(_deal(_felt(), n), CFG) == n
    assert P.street(_deal(_felt(), n), CFG) == name
