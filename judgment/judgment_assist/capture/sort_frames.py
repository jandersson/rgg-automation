"""Sort the captured screenshot library by game state (non-destructive).

Writes a manifest (state per frame) and prints counts. With --apply it also
hard-links each frame into data/screens/<state>/ so you can browse buckets
without duplicating disk (links, not copies). Originals are never moved/deleted.

    uv run python -m judgment_assist.capture.sort_frames                 # report + manifest
    uv run python -m judgment_assist.capture.sort_frames --apply         # also link into buckets
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter


def run(a):
    import cv2
    from ..vision.hud import HudReader
    from ..vision.state import classify

    cfg = json.load(open(a.config, encoding="utf-8"))
    hud = cfg.get("hud")
    if not hud:
        raise SystemExit(f"no 'hud' ROIs in {a.config} — run calibrate mark --game hud first")
    reader = HudReader(a.digits, min_confidence=0.5)
    D, P = hud["dealer_total"], hud["player_total"]

    frames = sorted(f for f in os.listdir(a.src)
                    if f.startswith("frame_") and f.endswith(".png"))
    if not frames:
        raise SystemExit(f"no frames in {a.src}")

    manifest, counts = {}, Counter()
    for fn in frames:
        img = cv2.imread(os.path.join(a.src, fn))
        if img is None:
            continue
        state, _f = classify(img, reader, D, P)
        manifest[fn] = state
        counts[state] += 1

    with open(a.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    total = sum(counts.values())
    print(f"classified {total} frames -> {a.manifest}")
    for state in ("decision", "in_hand", "modal", "other"):
        c = counts.get(state, 0)
        print(f"  {state:9} {c:4}  ({100*c/total:.0f}%)")
    card_frames = counts.get("decision", 0) + counts.get("in_hand", 0)
    print(f"  -> {card_frames} card-bearing frames usable for detector training")

    if a.apply:
        for state in counts:
            os.makedirs(os.path.join(a.src, state), exist_ok=True)
        linked = 0
        for fn, state in manifest.items():
            dst = os.path.join(a.src, state, fn)
            if not os.path.exists(dst):
                try:
                    os.link(os.path.join(a.src, fn), dst)  # hard link, no copy
                    linked += 1
                except OSError:
                    import shutil
                    shutil.copy2(os.path.join(a.src, fn), dst)
                    linked += 1
        print(f"linked {linked} frames into {a.src}/<state>/ (originals untouched)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist sort-frames")
    p.add_argument("--src", default="data/screens")
    p.add_argument("--config", default="config/regions.json")
    p.add_argument("--digits", default="data/digits")
    p.add_argument("--manifest", default="data/screens/_states.json")
    p.add_argument("--apply", action="store_true",
                   help="also hard-link frames into data/screens/<state>/ buckets")
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
