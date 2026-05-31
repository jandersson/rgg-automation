"""A small Tkinter GUI for fast visual confirmation of the vision pipeline's
guesses — so the recurring "is this prediction right?" loop isn't "open a montage
PNG and read tile numbers".

It is manifest-driven and label-agnostic, so it works for result banners now and
card ranks (or anything else) later:

    {"label_set": ["WIN", "LOSE", "PUSH", "BLACKJACK", "BUST"],
     "items": [{"image": "a.png", "pred": "WIN"}, ...],
     "out": "confirmed.json"}

Per item it shows the image and the predicted label. You either accept the
prediction (Enter), pick the correct label (its number key), or reject it as a
false positive (Backspace). Each choice auto-advances and saves to ``out`` as
``{image_path: confirmed_label_or_REJECT}``, so a wrong prediction is recorded as
a correction and a spurious detection as REJECT.

    uv run python -m judgment_assist.app.verify_gui --banners      # scan + verify result banners
    uv run python -m judgment_assist.app.verify_gui --manifest m.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os


class VerifyGUI:
    def __init__(self, items, label_set, out_path, title="verify"):
        import tkinter as tk
        self.tk = tk
        self.items = list(items)
        self.labels = list(label_set)
        self.out_path = out_path
        self.results = {}
        if os.path.exists(out_path):
            try:
                self.results = json.load(open(out_path, encoding="utf-8"))
            except Exception:
                self.results = {}
        self.i = 0
        self._photo = None

        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg="#101010")
        self.img = tk.Label(self.root, bg="#101010")
        self.img.pack(padx=8, pady=8)
        self.info = tk.Label(self.root, font=("Consolas", 15, "bold"), fg="#39ff14",
                             bg="#101010", justify="left")
        self.info.pack(fill="x", padx=8)
        keys = "   ".join(f"{n + 1}={lbl}" for n, lbl in enumerate(self.labels))
        self.help = tk.Label(
            self.root, bg="#101010", fg="#9aa", font=("Consolas", 10),
            text=f"Enter=accept pred   {keys}   Backspace=reject   <- -> nav   q=save&quit")
        self.help.pack(fill="x", padx=8, pady=(0, 8))

        self.root.bind("<Return>", lambda e: self._set(self._pred()))
        self.root.bind("<space>", lambda e: self._set(self._pred()))
        self.root.bind("<BackSpace>", lambda e: self._set("REJECT"))
        self.root.bind("<Left>", lambda e: self._nav(-1))
        self.root.bind("<Right>", lambda e: self._nav(1))
        self.root.bind("q", lambda e: self._quit())
        for n, lbl in enumerate(self.labels):
            self.root.bind(str(n + 1), lambda e, x=lbl: self._set(x))
        self._show()
        # make sure the window actually pops to the front (not hidden behind the terminal)
        self.root.update_idletasks()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(400, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def _pred(self):
        return self.items[self.i].get("pred")

    def _key(self):
        return self.items[self.i]["image"]

    def _show(self):
        item = self.items[self.i]
        try:
            self._photo = self.tk.PhotoImage(file=item["image"])
        except Exception:
            self._photo = None
        self.img.config(image=self._photo)
        done = sum(1 for v in self.results.values() if v)
        you = self.results.get(self._key(), "—")
        self.info.config(text=(f"[{self.i + 1}/{len(self.items)}]   pred: {self._pred()}"
                               f"      you: {you}      ({done} done)\n"
                               f"{os.path.basename(item['image'])}"))

    def _set(self, label):
        self.results[self._key()] = label
        self._save()
        if self.i < len(self.items) - 1:
            self._nav(1)
        else:
            self._show()

    def _nav(self, d):
        self.i = max(0, min(len(self.items) - 1, self.i + d))
        self._show()

    def _save(self):
        with open(self.out_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=1)

    def _quit(self):
        self._save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        self._save()
        return self.results


def build_banner_manifest(frames_dir="data/screens", results_dir="data/results",
                          out_dir="data/crops/_verify_banners", min_score=0.55):
    """Scan every frame for a result banner, dedupe consecutive hits into one
    instance per banner, crop each banner band to a viewable PNG, and write a
    manifest the GUI can drive. Returns the manifest dict."""
    import cv2
    from ..vision.result import ResultReader, _BAND
    rr = ResultReader(results_dir, min_score=min_score)
    os.makedirs(out_dir, exist_ok=True)

    def band_of(img):
        h, w = img.shape[:2]
        return (int(_BAND[0] * h), int(_BAND[1] * h), int(_BAND[2] * w), int(_BAND[3] * w))

    files = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    print(f"scanning {len(files)} frames for result banners...")
    dets = []
    for n, fn in enumerate(files):
        if n and n % 250 == 0:
            print(f"  {n}/{len(files)}...")
        img = cv2.imread(fn)
        if img is None:
            continue
        y0, y1, x0, x1 = band_of(img)
        band = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        best, score = None, min_score
        for cue, t in rr.templates.items():
            if t.shape[0] > band.shape[0] or t.shape[1] > band.shape[1]:
                continue
            s = float(cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max())
            if s >= score:
                best, score = cue, round(s, 2)
        if best:
            dets.append((int(os.path.basename(fn)[6:11]), best, score))

    instances = []  # collapse runs of the same cue on adjacent frames
    for num, cue, sc in dets:
        if instances and instances[-1][1] == cue and num - instances[-1][0] <= 4:
            if sc > instances[-1][2]:
                instances[-1] = (num, cue, sc)
        else:
            instances.append((num, cue, sc))

    items = []
    for num, cue, sc in instances:
        img = cv2.imread(os.path.join(frames_dir, f"frame_{num:05d}.png"))
        y0, y1, x0, x1 = band_of(img)
        crop = img[y0:y1, x0:x1]
        scale = 760.0 / crop.shape[1]
        crop = cv2.resize(crop, (760, max(1, int(crop.shape[0] * scale))))
        path = os.path.join(out_dir, f"{num:05d}_{cue}.png")
        cv2.imwrite(path, crop)
        items.append({"image": path, "pred": cue, "score": sc})

    manifest = {"label_set": ["WIN", "LOSE", "PUSH", "BLACKJACK", "BUST"],
                "items": items, "out": os.path.join(out_dir, "confirmed.json")}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist verify-gui")
    p.add_argument("--banners", action="store_true",
                   help="verify result banners (reuses the last scan unless --rescan)")
    p.add_argument("--rescan", action="store_true",
                   help="re-scan all frames for banners first (~20s) instead of reusing")
    p.add_argument("--manifest", help="verify an existing manifest JSON")
    a = p.parse_args(argv)
    if a.banners:
        mpath = "data/crops/_verify_banners/manifest.json"
        if a.rescan or not os.path.exists(mpath):
            man = build_banner_manifest()
        else:
            print(f"reusing {mpath} (pass --rescan to redo the frame scan)")
            with open(mpath, encoding="utf-8") as f:
                man = json.load(f)
        print(f"{len(man['items'])} banner instances -> launching window...")
    elif a.manifest:
        with open(a.manifest, encoding="utf-8") as f:
            man = json.load(f)
    else:
        raise SystemExit("pass --banners or --manifest <file>")
    if not man["items"]:
        raise SystemExit("nothing to verify")
    VerifyGUI(man["items"], man["label_set"], man["out"], title="verify banners").run()
    print(f"saved confirmations -> {man['out']}")


if __name__ == "__main__":
    main()
