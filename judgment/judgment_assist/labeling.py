"""Reusable data-labeling core for the whole project.

A *task* is a JSON file describing a batch of images to label and the label
schema; a *result* file maps each item id to the label(s) you gave it. The GUI
(``app/label.py``) is a thin view over ``LabelSession`` — all the navigation /
record / save / resume logic lives here so it is unit-testable without Tkinter.

Task schema::

    {
      "title": "Card ranks",
      "prompt": "What rank and colour is this card?",
      "fields": [                                  # one or more label dimensions
        {"name": "rank",  "labels": ["A","2","3","4","5","6","7","8","9","T","J","Q","K"]},
        {"name": "color", "labels": ["red","black"]}
      ],
      "allow_skip": true,                          # let the labeller skip unclear items
      "items": [{"id": "frame_00012#0", "image": "data/crops/x.png", "pred": "4"}],
      "out":   "data/crops/labels.json"
    }

Result schema (``out``)::

    {"frame_00012#0": {"rank": "4", "color": "red"}, "frame_00099#1": {"_skip": true}}

A single-field task behaves like a plain "pick one label per image" labeller; a
multi-field task collects every field before the item counts as complete.
"""
from __future__ import annotations

import json
import os

SKIP = "_skip"


def load_task(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def images_task(image_paths, labels, prompt, out, *, title="label", fields=None,
                preds=None, allow_skip=True):
    """Build a task dict over a flat list of image paths. ``labels`` is the
    single-field label set unless ``fields`` (a list of {name,labels}) is given.
    ``preds`` optionally maps image_path -> a predicted label to pre-show."""
    flds = fields or [{"name": "label", "labels": list(labels)}]
    preds = preds or {}
    items = [{"id": p, "image": p, **({"pred": preds[p]} if p in preds else {})}
             for p in image_paths]
    return {"title": title, "prompt": prompt, "fields": flds,
            "allow_skip": allow_skip, "items": items, "out": out}


class LabelSession:
    """Stateful, GUI-free labeling session. Loads any existing results from the
    task's ``out`` path so a session resumes where it left off."""

    def __init__(self, task):
        self.title = task.get("title", "label")
        self.prompt = task.get("prompt", "")
        self.fields = task["fields"]
        self.field_names = [f["name"] for f in self.fields]
        self.allow_skip = task.get("allow_skip", True)
        self.items = list(task["items"])
        self.out_path = task["out"]
        self.results = {}
        if self.out_path and os.path.exists(self.out_path):
            try:
                self.results = json.load(open(self.out_path, encoding="utf-8"))
            except Exception:
                self.results = {}
        self.i = 0
        self.active_field = 0   # which field the next label keypress fills

    # --- current item -----------------------------------------------------
    def current(self):
        return self.items[self.i] if self.items else None

    def current_id(self):
        it = self.current()
        return it["id"] if it else None

    def labels_for(self, field_idx):
        return self.fields[field_idx]["labels"]

    def value(self, field_name, item_id=None):
        rec = self.results.get(item_id or self.current_id(), {})
        return rec.get(field_name)

    def is_complete(self, item_id=None):
        rec = self.results.get(item_id or self.current_id())
        if not rec:
            return False
        if rec.get(SKIP):
            return True
        return all(n in rec for n in self.field_names)

    # --- mutate -----------------------------------------------------------
    def record(self, value, field_idx=None):
        """Set the active (or given) field to ``value``; advance the active
        field. Returns True once every field of the item is filled."""
        fidx = self.active_field if field_idx is None else field_idx
        rec = self.results.setdefault(self.current_id(), {})
        rec.pop(SKIP, None)
        rec[self.field_names[fidx]] = value
        self.active_field = min(fidx + 1, len(self.fields) - 1) if fidx + 1 < len(self.fields) else fidx
        # advance the active-field pointer to the first still-empty field
        self.active_field = next((k for k in range(len(self.fields))
                                  if self.field_names[k] not in rec), len(self.fields) - 1)
        return self.is_complete()

    def skip(self):
        if not self.allow_skip:
            return
        self.results[self.current_id()] = {SKIP: True}

    def clear(self):
        self.results.pop(self.current_id(), None)
        self.active_field = 0

    def goto(self, idx):
        self.i = max(0, min(len(self.items) - 1, idx))
        self.active_field = next((k for k in range(len(self.fields))
                                  if not self.value(self.field_names[k])), 0)
        return self.i

    def next(self):
        return self.goto(self.i + 1)

    def prev(self):
        return self.goto(self.i - 1)

    # --- io / status ------------------------------------------------------
    def progress(self):
        done = sum(1 for it in self.items if self.is_complete(it["id"]))
        return done, len(self.items)

    def summary(self):
        """Count of values per field (skips excluded)."""
        out = {n: {} for n in self.field_names}
        for rec in self.results.values():
            if rec.get(SKIP):
                continue
            for n in self.field_names:
                v = rec.get(n)
                if v is not None:
                    out[n][v] = out[n].get(v, 0) + 1
        return out

    def save(self):
        if not self.out_path:
            return
        parent = os.path.dirname(self.out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.out_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=1, sort_keys=True)
