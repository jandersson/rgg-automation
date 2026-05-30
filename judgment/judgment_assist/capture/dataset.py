"""'Watch me play' capture daemon — builds a screenshot library for training a
card-detection model (issue #5).

It grabs the game window's client area on an interval, but ONLY while Judgment
is the foreground window — so it never records the paused/dimmed state the game
shows when it loses focus (the failure mode that produced black frames before).
Near-duplicate frames are skipped so the library stays varied rather than 500
copies of the same idle table.

    uv run python -m judgment_assist.capture.dataset
    uv run python -m judgment_assist.capture.dataset --interval 1.5 --out data/screens

Stop with Ctrl-C. Re-running continues numbering from the existing files.
"""
from __future__ import annotations

import argparse
import os
import time

from .screen import ScreenGrabber
from .window import find_window_region, is_foreground


def _next_index(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    existing = [f for f in os.listdir(out_dir) if f.startswith("frame_") and f.endswith(".png")]
    nums = [int(f[6:-4]) for f in existing if f[6:-4].isdigit()]
    return (max(nums) + 1) if nums else 0


def _too_similar(a, b, thresh):
    """Mean absolute per-pixel difference below ``thresh`` -> treat as a dup."""
    if a is None or b is None or a.shape != b.shape:
        return False
    import numpy as np
    return float(np.mean(np.abs(a.astype("int16") - b.astype("int16")))) < thresh


def run(a):
    import cv2  # local import so the package imports without cv2 present

    out = a.out
    idx = _next_index(out)
    print(f"watch-and-capture: window={a.window!r} interval={a.interval}s out={out}")
    print("Only captures while the game is focused. Ctrl-C to stop.")
    saved = 0
    last = None
    waiting_msg = True
    try:
        with ScreenGrabber() as g:
            while True:
                if not is_foreground(a.window):
                    if waiting_msg:
                        print("  (waiting — focus Judgment to capture)")
                        waiting_msg = False
                    time.sleep(0.5)
                    continue
                waiting_msg = True
                reg = find_window_region(a.window)
                if reg is None or reg["width"] < 100:
                    time.sleep(a.interval)
                    continue
                frame = g.grab(reg)
                if _too_similar(frame, last, a.dup_thresh):
                    time.sleep(a.interval)
                    continue
                path = os.path.join(out, f"frame_{idx:05d}.png")
                cv2.imwrite(path, frame)
                last = frame
                idx += 1
                saved += 1
                if saved % 10 == 0:
                    print(f"  saved {saved} frames (latest {os.path.basename(path)})")
                time.sleep(a.interval)
    except KeyboardInterrupt:
        print(f"\nstopped. {saved} new frames in {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="judgment-assist dataset")
    p.add_argument("--window", default="Judgment", help="game window title substring")
    p.add_argument("--out", default="data/screens", help="output folder for frames")
    p.add_argument("--interval", type=float, default=1.5, help="seconds between grabs")
    p.add_argument("--dup-thresh", type=float, default=3.0,
                   help="skip frames more similar than this (mean abs pixel diff)")
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
