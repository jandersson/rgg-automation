"""Calibration helper — run against the live game (Judgment in borderless/
windowed mode) OR a saved screenshot, to build the ROI config and template
libraries.

Typical flow:
    py -m judgment_assist.capture.calibrate windows                 # find the title
    py -m judgment_assist.capture.calibrate templates --window Judgment   # build card library
    py -m judgment_assist.capture.calibrate mark --game blackjack --window Judgment
    py -m judgment_assist.capture.calibrate mark --game hud --image captures\shot1.jpg

`mark` and `templates` are interactive: an OpenCV window opens showing the
frame; drag a rectangle, press ENTER to accept (ESC/ENTER on empty to finish a
multi-select). ROIs are stored relative to the captured base (the game window's
client area when --window is used). Use --image to mark on a saved Steam F12
screenshot — this sidesteps the game's pause-on-focus-loss that blanks live
timed grabs.

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
# Blackjack uses rank-only templates, so its ROIs target the RANK GLYPH in each
# card's corner (suit-agnostic). Poker needs full cards, so it boxes whole cards.
SPECS = {
    "blackjack": [
        ("dealer_upcard", "single", "the RANK in the corner of the dealer's face-up card"),
        ("player_cards", "multi", "the RANK in the corner of each of YOUR cards"),
        ("dealer_cards", "multi", "the RANK corner of each DEALER card (optional, for counting)"),
    ],
    "poker": [
        ("hole_cards", "multi", "your TWO hole cards (whole card)"),
        ("board_cards", "multi", "all FIVE community card positions (whole card)"),
    ],
    # HUD badges: the numeric totals Judgment shows on a decision frame. Box the
    # NUMBER only (tight around the digits), not the whole badge or the "Total"
    # label above it.
    "hud": [
        ("dealer_total", "single", "the dealer's TOTAL number (top badge) — digits only"),
        ("player_total", "single", "YOUR hand TOTAL number (your badge) — digits only"),
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


def _grab_base(monitor, window, image=None):
    """Get the base frame to mark on. If ``image`` is given, load that saved
    screenshot (no live capture — sidesteps the game's pause-on-focus-loss).
    Otherwise grab the game window's client area, or the whole monitor."""
    if image:
        import cv2
        img = cv2.imread(image)
        if img is None:
            raise SystemExit(f"could not read image {image!r}")
        return img
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
    img = _grab_base(a.monitor, a.window, a.image)
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
    frame = _grab_base(a.monitor, a.window, a.image)
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
    # ROIs are relative to the window client area; record the window so live
    # capture targets it. When marking on a saved image there's no live window,
    # so default to the Judgment title (overridable with --window).
    if a.window or a.image:
        cfg["window"] = a.window or cfg.get("window") or "Judgment"
        cfg.pop("monitor", None)
    else:
        cfg["monitor"] = a.monitor or 1
    cfg[a.game] = {**cfg.get(a.game, {}), **result}
    _save_json(a.out, cfg)
    print(f"\nsaved {a.game} ROIs -> {a.out}")


def cmd_templates(a):
    import cv2
    from ..cards import parse_card, card_str, RANK_TO_INT

    if a.mode == "rank":
        hint = "rank (A K Q J T 9..2; blank=skip)"
        unit = "rank glyph (the card's corner)"

        def canon(raw):
            r = raw.strip().upper()
            if r not in RANK_TO_INT:
                raise ValueError(r)
            return r
    else:
        hint = "card (e.g. As, Td, 9c; blank=skip)"
        unit = "card"

        def canon(raw):
            return card_str(parse_card(raw))  # raises ValueError on bad input

    frame = _grab_base(a.monitor, a.window, a.image)
    print(f"Drag a box around each {unit} (ENTER between, ESC/empty to finish).")
    boxes = cv2.selectROIs("templates", frame, showCrosshair=False)
    cv2.destroyAllWindows()
    saved = 0
    for (x, y, w, h) in boxes:
        crop = frame[y:y + h, x:x + w]
        cv2.imshow("name this (focus this window, then type in the terminal)", crop)
        cv2.waitKey(300)
        raw = input(f"  {hint}: ").strip()
        cv2.destroyAllWindows()
        if not raw:
            continue
        try:
            name = canon(raw)
        except ValueError:
            print(f"    '{raw}' is not a valid {a.mode}; skipped")
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
        sp.add_argument("--image", default=None,
                        help="mark on a saved screenshot instead of a live grab "
                             "(e.g. a Steam F12 capture); avoids the game's pause")

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
    t.add_argument("--mode", choices=["card", "rank"], default="card",
                   help="rank = 13 corner glyphs (blackjack); card = full 52 (poker)")
    t.add_argument("--out", default="data/templates"); t.set_defaults(func=cmd_templates)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
