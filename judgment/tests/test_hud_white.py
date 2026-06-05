"""White-on-coloured digit reading (poker pot/chip/bet plates)."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from judgment_assist.vision.hud import HudReader


def _digit(d):
    img = np.full((40, 26, 3), (60, 40, 30), np.uint8)              # dark panel
    cv2.putText(img, str(d), (3, 33), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (245, 245, 245), 2)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def test_white_segmentation_finds_digits_and_ignores_gold(tmp_path):
    for d in range(10):                                   # templates only to construct
        cv2.imwrite(str(tmp_path / f"{d}.png"), _digit(d))
    hud = HudReader(str(tmp_path))
    panel = np.full((46, 190, 3), (70, 50, 30), np.uint8)
    cv2.putText(panel, "Bet", (4, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 180, 210), 2)  # gold label
    cv2.putText(panel, "152", (90, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (245, 245, 245), 2)  # white number
    boxes = hud._white_boxes(panel)
    assert len(boxes) == 3                               # the 3 white digits, segmented
    assert all(x > 80 for (x, y, w, h) in boxes)         # the saturated gold label is ignored
