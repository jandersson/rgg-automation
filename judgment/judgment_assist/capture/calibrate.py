"""Calibration helper — run against the live game to build the ROI config and
the card template library.

    # list monitors so you can pick the right index
    py -m judgment_assist.capture.calibrate monitors

    # grab a full-monitor screenshot to open in an editor and read off pixel coords
    py -m judgment_assist.capture.calibrate snapshot --out captures\frame.png

    # crop a card out of a saved frame to build a reference template
    py -m judgment_assist.capture.calibrate crop --in captures\frame.png \
        --region 880 720 70 96 --out data\templates\As.png

Workflow: snapshot the game, note each card's [left top width height] in an
image editor, crop one clean copy of every rank+suit you can find into
data/templates/<card>.png (e.g. As.png, Td.png), and record the live ROIs in
config/regions.json (copy from regions.example.json).
"""
import argparse
import os

from .screen import ScreenGrabber, _HAVE_DEPS


def _imwrite(path, img):
    import cv2
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cv2.imwrite(path, img)


def cmd_monitors(a):
    with ScreenGrabber() as g:
        for i, m in g.list_monitors():
            tag = "  (all monitors)" if i == 0 else ""
            print(f"  [{i}] {m}{tag}")


def cmd_snapshot(a):
    with ScreenGrabber(monitor=a.monitor) as g:
        img = g.grab()
    _imwrite(a.out, img)
    print(f"  saved {img.shape[1]}x{img.shape[0]} -> {a.out}")


def cmd_crop(a):
    import cv2
    img = cv2.imread(a.infile)
    if img is None:
        raise SystemExit(f"could not read {a.infile}")
    l, t, w, h = a.region
    crop = img[t:t + h, l:l + w]
    _imwrite(a.out, crop)
    print(f"  cropped [{l} {t} {w} {h}] -> {a.out}")


def main(argv=None):
    if not _HAVE_DEPS:
        raise SystemExit("calibration needs: pip install mss numpy opencv-python")
    p = argparse.ArgumentParser(prog="calibrate")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("monitors").set_defaults(func=cmd_monitors)

    s = sub.add_parser("snapshot")
    s.add_argument("--monitor", type=int, default=1)
    s.add_argument("--out", default="captures/frame.png")
    s.set_defaults(func=cmd_snapshot)

    c = sub.add_parser("crop")
    c.add_argument("--in", dest="infile", required=True)
    c.add_argument("--region", type=int, nargs=4, required=True,
                   metavar=("L", "T", "W", "H"))
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_crop)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
