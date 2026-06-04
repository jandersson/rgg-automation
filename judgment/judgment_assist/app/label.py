"""Reusable labeling GUI — present images, you label them.

    # label an existing task file
    uv run python -m judgment_assist.app.label --task data/crops/_cards/task.json

    # label every image in a folder with a fixed label set
    uv run python -m judgment_assist.app.label --dir some/imgs --labels WIN,LOSE,PUSH \
        --prompt "Which banner?" --out some/imgs/labels.json

    # build + label a card-rank/colour task from frames or screenshots
    uv run python -m judgment_assist.app.label --cards data/screens/frame_004*.png

Buttons cover every label (mouse), number keys 1-9 hit the active field's first
labels, Enter accepts the shown prediction, s=skip, Backspace=clear, arrows
navigate, q=save & quit. Saves incrementally to the task's ``out`` so it resumes.
The core (navigation/record/save) lives in ``judgment_assist.labeling`` and is
unit-tested; this module is only the Tkinter view + task builders.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os

from ..labeling import LabelSession, images_task, load_task, SKIP

_ACTIVE = "#39ff14"
_IDLE = "#2a2a2a"


def _photo(tk, path, max_w=560, max_h=440):
    """Load any image (jpg/png) via cv2 -> base64 PNG -> PhotoImage (no PIL dep)."""
    import cv2
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    s = min(max_w / w, max_h / h, 1.0)
    if s < 1.0:
        img = cv2.resize(img, (int(w * s), int(h * s)))
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))


class LabelerGUI:
    def __init__(self, session):
        import tkinter as tk
        self.tk = tk
        self.s = session
        self._photo = None
        self._btns = {}   # (field_idx, label) -> Button

        self.root = tk.Tk()
        self.root.title(self.s.title)
        self.root.configure(bg="#101010")
        self.imgL = tk.Label(self.root, bg="#101010")
        self.imgL.pack(padx=8, pady=8)
        self.prompt = tk.Label(self.root, text=self.s.prompt, font=("Consolas", 13, "bold"),
                               fg="#cde", bg="#101010", wraplength=620, justify="left")
        self.prompt.pack(fill="x", padx=8)

        self.field_frames = []
        for fidx, f in enumerate(self.s.fields):
            row = tk.Frame(self.root, bg="#101010")
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=f"{f['name']}:", width=7, anchor="w", fg="#9aa",
                     bg="#101010", font=("Consolas", 11)).pack(side="left")
            for n, lbl in enumerate(f["labels"]):
                key = f" [{n + 1}]" if (n < 9 and fidx == 0) else ""
                b = tk.Button(row, text=f"{lbl}{key}", font=("Consolas", 11),
                              bg=_IDLE, fg="#eee", activebackground="#0a5",
                              command=lambda x=lbl, fi=fidx: self._set(x, fi))
                b.pack(side="left", padx=2)
                self._btns[(fidx, lbl)] = b
            self.field_frames.append(row)

        self.info = tk.Label(self.root, font=("Consolas", 12), fg="#39ff14",
                             bg="#101010", justify="left")
        self.info.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(self.root, bg="#101010", fg="#9aa", font=("Consolas", 9),
                 text="click a label or 1-9   Enter=accept pred   s=skip   "
                      "Backspace=clear   <- -> nav   q=save&quit").pack(fill="x", padx=8, pady=(0, 8))

        self.root.bind("<Return>", lambda e: self._accept_pred())
        self.root.bind("s", lambda e: (self.s.skip(), self.s.save(), self._advance()))
        self.root.bind("<BackSpace>", lambda e: (self.s.clear(), self._show()))
        self.root.bind("<Left>", lambda e: (self.s.prev(), self._show()))
        self.root.bind("<Right>", lambda e: (self.s.next(), self._show()))
        self.root.bind("q", lambda e: self._quit())
        for n in range(9):
            self.root.bind(str(n + 1), lambda e, k=n: self._numkey(k))

        self._show()
        self.root.update_idletasks()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(400, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def _numkey(self, n):
        fidx = self.s.active_field
        labels = self.s.labels_for(fidx)
        if n < len(labels):
            self._set(labels[n], fidx)

    def _accept_pred(self):
        pred = (self.s.current() or {}).get("pred")
        if pred is not None and pred in self.s.labels_for(0):
            self._set(pred, 0)

    def _set(self, label, fidx):
        complete = self.s.record(label, fidx)
        self.s.save()
        if complete:
            self._advance()
        else:
            self._show()

    def _advance(self):
        if self.s.i < len(self.s.items) - 1:
            self.s.next()
        self._show()

    def _show(self):
        item = self.s.current()
        if item is None:
            return
        self._photo = _photo(self.tk, item["image"])
        self.imgL.config(image=self._photo, text="" if self._photo else "(image unreadable)")
        done, total = self.s.progress()
        for (fidx, lbl), b in self._btns.items():
            v = self.s.value(self.s.field_names[fidx])
            active = (fidx == self.s.active_field)
            b.config(bg=_ACTIVE if v == lbl else (_IDLE if not active else "#1f3a1f"),
                     fg="#000" if v == lbl else "#eee")
        vals = "  ".join(f"{n}={self.s.value(n) or '—'}" for n in self.s.field_names)
        pred = item.get("pred")
        ptxt = f"   pred:{pred}" if pred is not None else ""
        skipped = self.s.results.get(item["id"], {}).get(SKIP)
        self.info.config(text=(f"[{self.s.i + 1}/{total}]  {done} done{ptxt}   "
                               f"you: {'SKIP' if skipped else vals}\n{os.path.basename(item['image'])}"))

    def _quit(self):
        self.s.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        self.s.save()
        return self.s.results


# --- task builders --------------------------------------------------------

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]


def build_card_task(frame_glob_or_paths, out_dir="data/crops/_cards", width_frac=0.50,
                    pad=14, min_score=0.6, max_per_cluster=8):
    """Localize cards in each frame, crop each detected rank glyph (with a wide
    scan so down-and-left cascade edge cards are included), and write a task that
    asks for rank + colour per crop — the inputs needed to build/repair templates
    and red exemplars. The reader's current guess rides along as ``pred``. At most
    ``max_per_cluster`` highest-score glyphs per hand are kept (a hand is <=6
    cards), so a noisy cluster can't flood the batch."""
    import cv2
    from ..vision.locate import find_card_clusters
    from ..vision.recognizer import CardRecognizer
    from ..vision.reader import read_cluster_ranks
    from ..cards import INT_TO_RANK

    paths = (sorted(glob.glob(frame_glob_or_paths)) if isinstance(frame_glob_or_paths, str)
             else list(frame_glob_or_paths))
    rec = CardRecognizer("data/templates", mode="rank", min_confidence=min_score)
    os.makedirs(out_dir, exist_ok=True)
    items, preds = [], {}
    for fp in paths:
        im = cv2.imread(fp)
        if im is None:
            continue
        stem = os.path.splitext(os.path.basename(fp))[0]
        for ci, cl in enumerate(find_card_clusters(im)):
            glyphs = read_cluster_ranks(im, cl, rec, width_frac=width_frac, min_score=min_score)
            glyphs = sorted(glyphs, key=lambda g: -g[1])[:max_per_cluster]   # top by score
            glyphs = sorted(glyphs, key=lambda g: g[2][1])                   # back to top-to-bottom
            for gi, (lbl, _sc, (x, y, w, h)) in enumerate(glyphs):
                y0, y1 = max(0, y - pad), min(im.shape[0], y + h + pad)
                x0, x1 = max(0, x - pad), min(im.shape[1], x + w + pad)
                crop = im[y0:y1, x0:x1]
                if crop.size == 0:
                    continue
                crop = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
                cpath = os.path.join(out_dir, f"{stem}_c{ci}_g{gi}.png")
                cv2.imwrite(cpath, crop)
                items.append({"id": f"{stem}#{ci}.{gi}", "image": cpath,
                              "pred": INT_TO_RANK[lbl]})
                preds[cpath] = INT_TO_RANK[lbl]
    task = {"title": "Card rank + colour", "prompt": "Rank and colour of THIS card?",
            "fields": [{"name": "rank", "labels": RANKS},
                       {"name": "color", "labels": ["red", "black"]}],
            "allow_skip": True, "items": items, "out": os.path.join(out_dir, "labels.json")}
    with open(os.path.join(out_dir, "task.json"), "w", encoding="utf-8") as f:
        json.dump(task, f, indent=1)
    return task


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist label")
    p.add_argument("--task", help="an existing task JSON")
    p.add_argument("--dir", help="label every image in this folder")
    p.add_argument("--labels", help="comma-separated label set (with --dir)")
    p.add_argument("--prompt", default="Label this image", help="prompt (with --dir)")
    p.add_argument("--out", help="results JSON path (with --dir)")
    p.add_argument("--cards", nargs="+", help="frame paths/globs -> build a card rank+colour task")
    a = p.parse_args(argv)

    if a.task:
        task = load_task(a.task)
    elif a.cards:
        paths = [q for g in a.cards for q in (glob.glob(g) or [g])]
        task = build_card_task(paths)
        print(f"built card task: {len(task['items'])} crops -> {task['out']}")
    elif a.dir:
        if not a.labels:
            raise SystemExit("--dir needs --labels a,b,c")
        imgs = sorted(glob.glob(os.path.join(a.dir, "*.png")) + glob.glob(os.path.join(a.dir, "*.jpg")))
        out = a.out or os.path.join(a.dir, "labels.json")
        task = images_task(imgs, a.labels.split(","), a.prompt, out)
    else:
        raise SystemExit("pass --task, --dir, or --cards")
    if not task["items"]:
        raise SystemExit("no items to label")
    LabelerGUI(LabelSession(task)).run()
    print(f"saved labels -> {task['out']}")


if __name__ == "__main__":
    main()
