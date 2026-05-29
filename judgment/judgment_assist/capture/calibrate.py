"""Calibration helper — run against the live game (Judgment in borderless/
windowed mode) to build the ROI config and the card template library.

Typical flow:
    py -m judgment_assist.capture.calibrate windows                 # find the title
    py -m judgment_assist.capture.calibrate templates --window Judgment   # build card library
    py -m judgment_assist.capture.calibrate mark --game blackjack --window Judgment
    py -m judgment_assist.capture.calibrate mark --game poker --window Judgment

`mark` and `templates` are interactive: an OpenCV window opens showing the
current frame; drag a rectangle, press ENTER to accept (ESC/ENTER on empty to
finish a multi-select). ROIs are stored relative to the captured base (the game
window's client area when --window is used), so they survive moving the window.

Lower-level commands (manual pixel coords) are also available:
    calibrate monitors
    calibrate snapshot --window Judgment --out captures\frame.png
    calibrate crop --in captures\frame.png --region 880 720 70 96 --out data\templates\As.png
"""
import argparse
import json
import os

from .screen import ScreenGrabber, _HAVE_DEPS

# Regions to mark per game. kind: "single" -> one box, "multi" -> many boxes.
SPECS = {
    "blackjack": [
        ("dealer_upcard", "single", "dealer's face-up card"),
        ("player_cards", "multi", "each of YOUR card positions"),
        ("dealer_cards", "multi", "each DEALER card position (optional, for counting)"),
    ],
    "poker": [
        ("hole_cards", "multi", "your TWO hole cards"),
        ("board_cards", "multi", "all FIVE community card positions"),
    ],
}


def _imwrite(path, img):
    import cv2
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cv2.imwrite(path, img)


def _load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _grab_base(monitor, window):
    """Capture the base frame: the game window's client area if --window is
    given, else the whole monitor."""
    with ScreenGrabber(monitor=monitor or 1) as g:
        if window:
            from .window import find_window_region
            reg = find_window_region(window)
            if reg is None:
                raise SystemExit(f"no visible window matching {window!r} "
                                 f"(try: calibrate windows)")
            return g.grab(reg)
        return g.grab()


def _box_list(rois):
    return [[int(x), int(y), int(w), int(h)] for (x, y, w, h) in rois]


# ---------------------------------------------------------------- commands ---
def cmd_monitors(a):
    with ScreenGrabber() as g:
        for i, m in g.list_monitors():
            print(f"  [{i}] {m}{'  (all monitors)' if i == 0 else ''}")


def cmd_windows(a):
    from .window import list_windows
    for hwnd, title in list_windows():
        print(f"  0x{hwnd:08X}  {title}")


def cmd_snapshot(a):
    img = _grab_base(a.monitor, a.window)
    _imwrite(a.out, img)
    print(f"  saved {img.shape[1]}x{img.shape[0]} -> {a.out}")


def cmd_crop(a):
    import cv2
    img = cv2.imread(a.infile)
    if img is None:
        raise SystemExit(f"could not read {a.infile}")
    l, t, w, h = a.region
    _imwrite(a.out, img[t:t + h, l:l + w])
    print(f"  cropped [{l} {t} {w} {h}] -> {a.out}")


def cmd_mark(a):
    import cv2
    frame = _grab_base(a.monitor, a.window)
    result = {}
    for key, kind, desc in SPECS[a.game]:
        print(f"\n[{key}] drag a box around {desc}; ENTER to accept"
              + (", ESC/empty when done" if kind == "multi" else ""))
        if kind == "single":
            x, y, w, h = cv2.selectROI("calibrate", frame, showCrosshair=False)
            result[key] = [int(x), int(y), int(w), int(h)]
        else:
            result[key] = _box_list(cv2.selectROIs("calibrate", frame, showCrosshair=False))
        cv2.destroyAllWindows()

    cfg = _load_json(a.out)
    if a.window:
        cfg["window"] = a.window
        cfg.pop("monitor", None)
    else:
        cfg["monitor"] = a.monitor or 1
    cfg[a.game] = {**cfg.get(a.game, {}), **result}
    _save_json(a.out, cfg)
    print(f"\nsaved {a.game} ROIs -> {a.out}")


def cmd_templates(a):
    import cv2
    frame = _grab_base(a.monitor, a.window)
    print("Drag a box around each visible card (ENTER between, ESC/empty to finish).")
    boxes = cv2.selectROIs("templates", frame, showCrosshair=False)
    cv2.destroyAllWindows()
    saved = 0
    for (x, y, w, h) in boxes:
        crop = frame[y:y + h, x:x + w]
        cv2.imshow("name this card (focus this window, then type in the terminal)", crop)
        cv2.waitKey(300)
        name = input("  card (e.g. As, Td, 9c; blank=skip): ").strip()
        cv2.destroyAllWindows()
        if not name:
            continue
        _imwrite(os.path.join(a.out, name + ".png"), crop)
        saved += 1
        print(f"    saved {name}.png")
    print(f"\n{saved} template(s) -> {a.out}")


def main(argv=None):
    if not _HAVE_DEPS:
        raise SystemExit("calibration needs: pip install mss numpy opencv-python")
    p = argparse.ArgumentParser(prog="calibrate")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("monitors").set_defaults(func=cmd_monitors)
    sub.add_parser("windows").set_defaults(func=cmd_windows)

    def add_source(sp):
        sp.add_argument("--monitor", type=int, default=None)
        sp.add_argument("--window", default=None, help="window title substring")

    s = sub.add_parser("snapshot"); add_source(s)
    s.add_argument("--out", default="captures/frame.png"); s.set_defaults(func=cmd_snapshot)

    c = sub.add_parser("crop")
    c.add_argument("--in", dest="infile", required=True)
    c.add_argument("--region", type=int, nargs=4, required=True, metavar=("L", "T", "W", "H"))
    c.add_argument("--out", required=True); c.set_defaults(func=cmd_crop)

    m = sub.add_parser("mark"); add_source(m)
    m.add_argument("--game", choices=list(SPECS), required=True)
    m.add_argument("--out", default="config/regions.json"); m.set_defaults(func=cmd_mark)

    t = sub.add_parser("templates"); add_source(t)
    t.add_argument("--out", default="data/templates"); t.set_defaults(func=cmd_templates)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
