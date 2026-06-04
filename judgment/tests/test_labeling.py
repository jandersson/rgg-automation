"""Tests for the GUI-free labeling core."""
import json

import pytest

from judgment_assist.labeling import LabelSession, images_task, SKIP


def test_glyph_color_red_vs_black():
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from judgment_assist.app.label import glyph_color
    cream = np.full((120, 90, 3), (205, 215, 210), np.uint8)  # BGR card body
    red, black = cream.copy(), cream.copy()
    cv2.putText(red, "4", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (40, 40, 200), 6)   # red ink
    cv2.putText(black, "4", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (30, 30, 30), 6)  # black ink
    assert glyph_color(red) == "red"
    assert glyph_color(black) == "black"


def _single(tmp_path):
    out = str(tmp_path / "labels.json")
    task = images_task(["a.png", "b.png", "c.png"], ["WIN", "LOSE", "PUSH"],
                       "Which?", out)
    return LabelSession(task), out


def test_images_task_shape(tmp_path):
    task = images_task(["a.png", "b.png"], ["X", "Y"], "?", str(tmp_path / "o.json"),
                       preds={"a.png": "X"})
    assert len(task["items"]) == 2
    assert task["items"][0] == {"id": "a.png", "image": "a.png", "pred": "X"}
    assert task["fields"] == [{"name": "label", "labels": ["X", "Y"]}]


def test_single_field_record_completes_and_advances(tmp_path):
    s, _ = _single(tmp_path)
    assert s.current_id() == "a.png"
    assert s.record("WIN") is True            # single field -> complete at once
    assert s.is_complete("a.png")
    assert s.value("label", "a.png") == "WIN"
    s.next()
    assert s.current_id() == "b.png"


def test_multi_field_requires_all_fields(tmp_path):
    out = str(tmp_path / "l.json")
    task = images_task(["x.png"], None, "?", out,
                       fields=[{"name": "rank", "labels": ["4", "9"]},
                               {"name": "color", "labels": ["red", "black"]}])
    s = LabelSession(task)
    assert s.active_field == 0
    assert s.record("4") is False             # rank set, colour still missing
    assert s.active_field == 1                 # advanced to the empty field
    assert s.record("red") is True             # now complete
    assert s.results["x.png"] == {"rank": "4", "color": "red"}


def test_skip_and_clear(tmp_path):
    s, _ = _single(tmp_path)
    s.skip()
    assert s.is_complete("a.png") and s.results["a.png"] == {SKIP: True}
    s.clear()
    assert "a.png" not in s.results and not s.is_complete("a.png")


def test_save_and_resume(tmp_path):
    s, out = _single(tmp_path)
    s.record("WIN"); s.next(); s.record("LOSE"); s.save()
    # a fresh session over the same task picks up the saved labels
    task = images_task(["a.png", "b.png", "c.png"], ["WIN", "LOSE", "PUSH"], "Which?", out)
    s2 = LabelSession(task)
    assert s2.value("label", "a.png") == "WIN"
    assert s2.progress() == (2, 3)
    # resumed item starts on its first empty field
    assert json.load(open(out))["b.png"] == {"label": "LOSE"}


def test_pred_for_scalar_and_dict(tmp_path):
    # scalar pred applies to the first field only
    task = images_task(["a.png"], None, "?", str(tmp_path / "s.json"),
                       fields=[{"name": "rank", "labels": ["4"]},
                               {"name": "color", "labels": ["red", "black"]}],
                       preds={"a.png": "4"})
    s = LabelSession(task)
    assert s.pred_for("rank") == "4" and s.pred_for("color") is None
    # dict pred carries a value per field
    s.items[0]["pred"] = {"rank": "4", "color": "red"}
    assert s.pred_for("rank") == "4" and s.pred_for("color") == "red"


def test_accept_predictions_keeps_corrections(tmp_path):
    task = images_task(["x.png"], None, "?", str(tmp_path / "a.json"),
                       fields=[{"name": "rank", "labels": ["3", "9"]},
                               {"name": "color", "labels": ["red", "black"]}])
    task["items"][0]["pred"] = {"rank": "9", "color": "red"}   # a wrong rank prediction
    s = LabelSession(task)
    s.record("3", 0)                       # user corrects rank 9 -> 3
    assert s.accept_predictions() is True  # fills the empty colour, completes
    assert s.value("rank") == "3"          # correction kept, NOT overwritten by pred 9
    assert s.value("color") == "red"       # empty field took the prediction


def test_accept_predictions_fills_all_when_untouched(tmp_path):
    task = images_task(["y.png"], None, "?", str(tmp_path / "b.json"),
                       fields=[{"name": "rank", "labels": ["4"]},
                               {"name": "color", "labels": ["red", "black"]}])
    task["items"][0]["pred"] = {"rank": "4", "color": "black"}
    s = LabelSession(task)
    assert s.accept_predictions() is True
    assert s.value("rank") == "4" and s.value("color") == "black"


def test_summary_excludes_skips(tmp_path):
    s, _ = _single(tmp_path)
    s.record("WIN"); s.next(); s.record("WIN"); s.next(); s.skip()
    assert s.summary() == {"label": {"WIN": 2}}
