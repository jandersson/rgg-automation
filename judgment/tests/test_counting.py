"""Tests for the Hi-Lo counter and the frame-by-frame ShoeCounter dedup."""
from judgment_assist.blackjack.counting import HiLoCounter, ShoeCounter


def test_hilo_running_and_true_count():
    c = HiLoCounter(decks=1)
    c.see_many([2, 3, 4, 5, 6])   # five +1
    assert c.running == 5
    c.see_many([10, 11, 12, 13, 14])  # five -1
    assert c.running == 0


def _feed(sc, frames):
    for f in frames:
        sc.observe(f)


def test_counts_each_card_once_over_many_frames():
    sc = ShoeCounter(decks=6, confirm=2)
    _feed(sc, [[6, 5]] * 6)        # one hand held for 6 frames
    assert sc.seen == 2            # counted once, not 6x
    assert sc.running == 2         # 6 and 5 are both +1


def test_hit_adds_only_the_new_card():
    sc = ShoeCounter(confirm=2)
    _feed(sc, [[7, 9]] * 2)        # 7,9 both Hi-Lo 0
    assert sc.seen == 2 and sc.running == 0
    _feed(sc, [[7, 9, 4]] * 2)     # a hit: +4
    assert sc.seen == 3 and sc.running == 1


def test_table_clear_ends_hand_but_count_persists():
    sc = ShoeCounter(confirm=2, clear_frames=2)
    _feed(sc, [[5, 6]] * 2)        # +2
    _feed(sc, [[], []])            # table clears -> hand over
    assert sc.hands == 1
    _feed(sc, [[5, 6]] * 2)        # next hand: same ranks count again
    assert sc.seen == 4 and sc.running == 4


def test_confirm_gate_ignores_one_frame_blip():
    sc = ShoeCounter(confirm=2)
    _feed(sc, [[6]])               # single frame -> not yet trusted
    assert sc.seen == 0
    _feed(sc, [[6]])               # repeated -> credited
    assert sc.seen == 1


def test_reset_zeroes_everything():
    sc = ShoeCounter(confirm=1)
    _feed(sc, [[10, 10]])          # two tens -> -2
    assert sc.running == -2 and sc.seen == 2
    sc.reset()
    assert sc.running == 0 and sc.seen == 0
