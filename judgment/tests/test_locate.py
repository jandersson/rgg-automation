"""Deterministic smoke/regression tests for the blackjack card localizer.

Synthetic frames (no game captures needed) lock in the behaviours the localizer
promises:
  * a solid card-sized region is found;
  * a *cream* card (not bright white) is still found — guards the threshold bug
    where the gate (S<80, V>150) rejected the real cards (sampled ~S=87, V=110);
  * thin printed-text strokes are rejected (erosion dissolves them);
  * cascaded cards collapse to a single cluster.
Real-frame coverage (cards found in 72/72 in_hand frames) is validated
separately against data/screens, not in unit tests.
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


def _hsv_bgr(h, s, v):
    return tuple(int(c) for c in cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0])


def test_solid_card_is_found():
    f = _frame()
    x, y, w, h = 800, 350, 100, 150
    f[y:y + h, x:x + w] = (250, 250, 250)
    clusters = find_card_clusters(f)
    assert len(clusters) == 1
    cx, cy, cw, ch = clusters[0]
    assert abs(cx - x) <= 16 and abs(cy - y) <= 16


def test_cream_card_is_found():
    """Regression: the real cards are cream (passes V>=140,S<=90 but failed the
    old V>150,S<80 gate). A cream-filled card must still be located."""
    f = _frame()
    cream = _hsv_bgr(15, 85, 150)   # in the new gate's band, outside the old one
    f[350:500, 800:900] = cream
    assert len(find_card_clusters(f)) == 1


def test_thin_text_is_rejected():
    f = _frame()
    for i in range(6):
        cv2.line(f, (600 + i * 60, 300), (640 + i * 60, 360), (250, 250, 250), 3)
    assert find_card_clusters(f) == []


def test_blank_felt_has_no_cards():
    assert find_card_clusters(_frame()) == []


def test_cascade_is_one_cluster():
    f = _frame()
    for x, y in [(800, 350), (812, 392)]:
        f[y:y + 150, x:x + 100] = (250, 250, 250)
    assert len(find_card_clusters(f)) == 1


def test_corner_indices_on_a_synthetic_cascade():
    f = _frame()
    for x, y in [(800, 350), (812, 392)]:
        f[y:y + 150, x:x + 100] = (250, 250, 250)
        cv2.putText(f, "7", (x + 6, y + 36), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (20, 20, 20), 2)
    clusters = find_card_clusters(f)
    assert len(clusters) == 1
    assert len(corner_index_boxes(f, clusters[0])) >= 1
