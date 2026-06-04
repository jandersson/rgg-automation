"""Tests for the GUI-free labeling core."""
import json

from judgment_assist.labeling import LabelSession, images_task, SKIP


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


def test_summary_excludes_skips(tmp_path):
    s, _ = _single(tmp_path)
    s.record("WIN"); s.next(); s.record("WIN"); s.next(); s.skip()
    assert s.summary() == {"label": {"WIN": 2}}
