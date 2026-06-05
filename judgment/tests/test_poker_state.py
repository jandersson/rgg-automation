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


# ----------------------------------------------------------- to-call math -----
def test_to_call_basic():
    # highest active bet 20, hero already in 15 -> owes 5
    assert P.to_call([20, 20, 20], [True, True, True], 15) == 5


def test_to_call_never_negative():
    # hero has out-bet the table (raised) -> nothing to call
    assert P.to_call([70, 0, 0], [True, False, False], 80) == 0


def test_to_call_ignores_folded_and_unreadable():
    # a folded seat showing a stale high bet must not set the price...
    assert P.to_call([200, 40, None], [False, True, True], 10) == 30
    # ...and a None (unreadable plate) is skipped, not treated as 0
    assert P.to_call([None, None, 25], [True, True, True], 0) == 25


def test_to_call_zero_when_no_live_bets():
    assert P.to_call([], [], 0) == 0
    assert P.to_call([0, 0, 0], [True, True, True], 0) == 0


# -------------------------------------------------------- folded opponents ----
def _banner(hue):
    """A 42x95 banner crop whose icon area is painted at the given OpenCV hue."""
    hsv = np.zeros((42, 95, 3), np.uint8)
    hsv[8:34, 25:70] = (hue, 200, 200)          # ~1170 px icon block
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_opp_folded_detects_cyan_icon():
    assert P.opp_folded(_banner(102)) is True    # cyan fold chevron
    assert P.opp_folded(_banner(60)) is False     # green call icon
    assert P.opp_folded(_banner(0)) is False      # red raise icon
    assert P.opp_folded(np.zeros((42, 95, 3), np.uint8)) is False   # blank banner


def test_opp_active_flags_from_banners():
    cfg = {"opp_banner": [[0, 0, 95, 42], [100, 0, 95, 42], [200, 0, 95, 42]]}
    frame = np.zeros((42, 300, 3), np.uint8)
    frame[0:42, 100:195] = _banner(102)          # middle opponent folded
    assert P.opp_active(frame, cfg) == [True, False, True]


def test_table_state_combines_reads_and_folds():
    class FakeReader:   # returns a bet per ROI key by position; pot/my-bet fixed
        def read_roi(self, frame, roi, white=False):
            return {"pot": 225, "my": 80, "o0": 0, "o1": 70, "o2": 0}[roi], 1.0

    cfg = {"corner": CFG["corner"], "board": CFG["board"],
           "pot": "pot", "bet": "my",
           "opp_bet": ["o0", "o1", "o2"],
           "opp_banner": [[0, 0, 95, 42], [100, 0, 95, 42], [200, 0, 95, 42]]}
    frame = _deal(_felt(), 5)                     # river
    frame[0:42, 0:95] = _banner(102)             # opp0 folded
    frame[0:42, 200:295] = _banner(102)          # opp2 folded
    st = P.table_state(frame, cfg, FakeReader())
    assert st["street"] == "river" and st["pot"] == 225
    assert st["opp_active"] == [False, True, False] and st["n_active"] == 1
    assert st["to_call"] == 0                      # only live bet 70 < hero's 80
