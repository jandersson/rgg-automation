"""Tests for the HUD digit reader, using synthetic badges so they run without
the game. Skipped if numpy/opencv aren't installed."""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from judgment_assist.vision.hud import HudReader, _binarize


def _digit_img(text, w=30, h=46):
    img = np.zeros((h, w, 3), np.uint8)
    cv2.putText(img, text, (4, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    return img


def _tight_gray(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    thr = _binarize(gray)
    ys, xs = np.where(thr > 0)
    return gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _build_templates(tmp_path):
    d = tmp_path / "digits"
    d.mkdir()
    for n in range(10):
        cv2.imwrite(str(d / f"{n}.png"), _tight_gray(_digit_img(str(n))))
    return d


def _badge(number):
    """A dark badge with the number drawn in light digits, like the in-game HUD."""
    s = str(number)
    w = 34 * len(s) + 24
    img = np.full((70, w, 3), 28, np.uint8)
    cv2.putText(img, s, (12, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (240, 240, 240), 3)
    return img


def test_reads_totals(tmp_path):
    r = HudReader(str(_build_templates(tmp_path)), min_confidence=0.4)
    for total in [5, 8, 10, 16, 17, 20, 21, 11]:
        val, conf = r.read(_badge(total))
        assert val == total, (total, val, conf)


def test_empty_badge_returns_none(tmp_path):
    r = HudReader(str(_build_templates(tmp_path)), min_confidence=0.4)
    blank = np.full((70, 90, 3), 28, np.uint8)   # dark badge, no digits
    val, _conf = r.read(blank)
    assert val is None


def test_missing_templates_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError):
        HudReader(str(empty))
