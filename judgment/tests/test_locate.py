"""Deterministic smoke tests for the blackjack card localizer.

These use synthetic frames (no game captures needed) to lock in the two
behaviours the localizer promises: a solid card-sized white rectangle is found,
and thin printed-text strokes are rejected by the fill-ratio filter.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from judgment_assist.vision.locate import find_card_clusters, corner_index_boxes

H, W = 1080, 1920
FELT = (70, 120, 40)  # BGR green


def _frame():
    f = np.zeros((H, W, 3), np.uint8)
    f[:] = FELT
    return f


def test_solid_card_is_found():
    f = _frame()
    # a card-sized solid white rectangle inside the play area
    x, y, w, h = 800, 350, 90, 130
    f[y:y + h, x:x + w] = (250, 250, 250)
    clusters = find_card_clusters(f)
    assert len(clusters) == 1
    cx, cy, cw, ch = clusters[0]
    assert abs(cx - x) <= 12 and abs(cy - y) <= 12
    assert abs(cw - w) <= 20 and abs(ch - h) <= 20


def test_thin_text_is_rejected():
    f = _frame()
    # thin white strokes (like printed felt text) span a wide bbox but fill little
    for i in range(6):
        cv2.line(f, (600 + i * 60, 300), (640 + i * 60, 360), (250, 250, 250), 3)
    assert find_card_clusters(f) == []


def test_blank_felt_has_no_cards():
    assert find_card_clusters(_frame()) == []


def test_corner_indices_on_a_synthetic_cascade():
    f = _frame()
    # two cascading cards, each with a dark rank glyph in its top-left corner
    for k, (x, y) in enumerate([(800, 350), (812, 392)]):
        f[y:y + 130, x:x + 90] = (250, 250, 250)
        cv2.putText(f, "7", (x + 6, y + 34), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (20, 20, 20), 2)
    clusters = find_card_clusters(f)
    assert len(clusters) == 1
    boxes = corner_index_boxes(f, clusters[0])
    assert len(boxes) >= 1   # at least the exposed top card's index
