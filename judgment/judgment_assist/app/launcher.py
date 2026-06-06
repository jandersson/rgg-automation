"""GUI launcher for the live overlays — pick the game, set the flags, launch.

    uv run python -m judgment_assist.app.launcher

A small tkinter form (no extra deps, same toolkit as the overlay) over
``app.live``'s flags. The advisor runs as a single always-on-top overlay window —
advice plus the poker card-entry box, no console. The launcher stays open so you
can tweak and relaunch (and closing it stops the overlays it started).

``build_argv`` (the flag→argv mapping) is a pure function so it can be unit
tested without a display; the tkinter UI is a thin shell around it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .labels_tab import LabelsTab

# Project root (judgment/) — two levels up from this file (app/ -> judgment_assist/
# -> judgment/). Used as the child's cwd so the default relative paths in the
# flags (config/regions.json, data/...) resolve no matter where the GUI is run.
ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {
    "game": "poker",
    "config": "config/regions.json",
    "interval": 0.7,
    "min_confidence": 0.6,
    "x": 40,
    "y": 460,               # clear of every poker reader ROI; (40,40) sat on
                            # opp_bet[0] and made the reader read the overlay itself
    "overlay": True,        # False -> --no-overlay (console only)
    # poker
    "detect": True,         # False -> --no-detect
    "reader": "CNN",        # card reader: "CNN" (default, stronger; falls back to HOG if no
                            # model file) or "HOG" (learns from corrections as you play)
    "learn": True,          # False -> --no-learn
    "confirm_key": "insert",   # global confirm hotkey (controller back button)
    "opp": 3,               # Judgment poker is 4-handed (you + 3)
    "iters": 12000,
    # blackjack
    "decks": 6,
    "count": False,         # True -> --count
    "db": True,             # False -> --no-db
    "log": "",              # path -> --log
}


def build_argv(o):
    """Map an options dict to the ``app.live`` argument vector. Only emits the
    flags relevant to the selected game, and only the non-default booleans, so the
    resulting command is minimal and readable."""
    g = o["game"]
    argv = [g,
            "--config", str(o["config"]),
            "--interval", str(o["interval"]),
            "--min-confidence", str(o["min_confidence"]),
            "--x", str(o["x"]),
            "--y", str(o["y"])]
    if not o["overlay"]:
        argv.append("--no-overlay")
    if g == "poker":
        argv += ["--opp", str(o["opp"]), "--iters", str(o["iters"])]
        if not o["detect"]:
            argv.append("--no-detect")
        if not o["learn"]:
            argv.append("--no-learn")
        argv += ["--confirm-key", str(o["confirm_key"])]
    else:
        argv += ["--decks", str(o["decks"])]
        if o["count"]:
            argv.append("--count")
        if not o["db"]:
            argv.append("--no-db")
        if str(o.get("log") or "").strip():
            argv += ["--log", o["log"]]
    return argv


def launch(argv):
    """Spawn ``app.live`` with ``argv``. Card entry is now in the overlay window
    itself, so no console is needed — suppress the console window on Windows.
    Returns the Popen handle."""
    cmd = [sys.executable, "-m", "judgment_assist.app.live", *argv]
    kwargs = {"cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


def summarize(o):
    """Plain-English description of what Launch will do (for the GUI preview)."""
    g = o["game"]
    if g == "poker":
        bits = ["auto-detect hole cards " + ("ON" if o["detect"] else "OFF"),
                "learn from corrections " + ("ON" if o["learn"] else "OFF"),
                f"assume {o['opp']} opponents when unsure"]
    else:
        bits = [f"{o['decks']}-deck shoe",
                "Hi-Lo counting " + ("ON" if o["count"] else "OFF"),
                "session logging " + ("ON" if o["db"] else "OFF")]
    where = "print to console only" if not o["overlay"] else f"floating overlay at ({o['x']}, {o['y']})"
    return (f"{g.capitalize()} advisor: " + ", ".join(bits) + ".\n"
            f"{where.capitalize()}, re-reading the screen every {o['interval']}s.")


def _save_tick_error(tb, frame):
    """Dump a tick traceback (and the frame that triggered it) to
    ``data/_tick_err/`` so an intermittent read crash can be reproduced offline.
    Best-effort: any failure here is swallowed so it can't break the loop."""
    try:
        import time
        d = ROOT / "data" / "_tick_err"
        d.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        (d / f"{ts}.txt").write_text(tb, encoding="utf-8")
        if frame is not None and getattr(frame, "size", 0):
            import cv2
            cv2.imwrite(str(d / f"{ts}.png"), frame)
        print(f"  (saved tick-error frame + traceback to data/_tick_err/{ts}.*)")
    except Exception:                             # noqa: BLE001
        pass


class _GuiWriter:
    """A stdout stand-in that appends to a tk Text widget (and mirrors to the real
    stdout if there is one). Writes happen on the tk thread, so direct update is
    safe."""
    def __init__(self, widget, mirror=None):
        self.widget, self.mirror = widget, mirror

    def write(self, s):
        if self.mirror:
            try:
                self.mirror.write(s)
            except Exception:
                pass
        try:
            self.widget.configure(state="normal")
            self.widget.insert("end", s)
            self.widget.see("end")
            self.widget.configure(state="disabled")
        except Exception:
            pass

    def flush(self):
        if self.mirror:
            try:
                self.mirror.flush()
            except Exception:
                pass


def terminate_all(procs):
    """Terminate any still-running spawned overlays. Returns how many were killed."""
    n = 0
    for p in procs:
        if p.poll() is None:
            try:
                p.terminate()
                n += 1
            except Exception:
                pass
    return n


# --------------------------------------------------------------------- GUI ---
class LauncherApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.procs = []
        root.title("RGG advisor launcher")
        root.resizable(False, False)

        # Two tabs: "Play" (the setup form + live corrections + log) and "Review"
        # (the confirmed/corrected cards banked this session, so you can check what
        # got learned). The body widgets below live on the Play tab, not root.
        self.nb = ttk.Notebook(root)
        self.nb.grid(row=0, column=0, sticky="nsew")
        self.tab_play = ttk.Frame(self.nb)
        self.tab_labels = ttk.Frame(self.nb)
        self.nb.add(self.tab_play, text="Play")
        self.nb.add(self.tab_labels, text="Labels")

        self.v = {
            "game": tk.StringVar(value=DEFAULTS["game"]),
            "config": tk.StringVar(value=DEFAULTS["config"]),
            "interval": tk.StringVar(value=str(DEFAULTS["interval"])),
            "min_confidence": tk.StringVar(value=str(DEFAULTS["min_confidence"])),
            "x": tk.StringVar(value=str(DEFAULTS["x"])),
            "y": tk.StringVar(value=str(DEFAULTS["y"])),
            "overlay": tk.BooleanVar(value=DEFAULTS["overlay"]),
            "detect": tk.BooleanVar(value=DEFAULTS["detect"]),
            "reader": tk.StringVar(value=DEFAULTS["reader"]),
            "learn": tk.BooleanVar(value=DEFAULTS["learn"]),
            "confirm_key": tk.StringVar(value=DEFAULTS["confirm_key"]),
            "opp": tk.StringVar(value=str(DEFAULTS["opp"])),
            "iters": tk.StringVar(value=str(DEFAULTS["iters"])),
            "decks": tk.StringVar(value=str(DEFAULTS["decks"])),
            "count": tk.BooleanVar(value=DEFAULTS["count"]),
            "db": tk.BooleanVar(value=DEFAULTS["db"]),
            "log": tk.StringVar(value=DEFAULTS["log"]),
        }
        for var in self.v.values():
            var.trace_add("write", lambda *_: self._refresh())

        pad = {"padx": 8, "pady": 3}
        body = self.tab_play
        # game selector
        gf = ttk.LabelFrame(body, text="Game")
        gf.grid(row=0, column=0, sticky="ew", **pad)
        for i, g in enumerate(("poker", "blackjack")):
            ttk.Radiobutton(gf, text=g.capitalize(), value=g,
                            variable=self.v["game"]).grid(row=0, column=i, sticky="w", **pad)
        self._help(gf, 1, "Poker = Hold'em equity + pot-odds.   Blackjack = basic-strategy advice.",
                   colspan=3)

        # the overlay (one window: advice + the card-entry box)
        ov = ttk.LabelFrame(body, text="Overlay")
        ov.grid(row=1, column=0, sticky="ew", **pad)
        self._help(ov, 0, "A floating box over the game shows the advice (display only). "
                          "Poker card corrections happen here in the launcher, below.")
        ttk.Label(ov, text="Position:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(ov, textvariable=self.v["x"], width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(ov, text="across,").grid(row=1, column=2, sticky="w")
        ttk.Entry(ov, textvariable=self.v["y"], width=5).grid(row=1, column=3, sticky="w")
        ttk.Label(ov, text="down  (pixels from the top-left)").grid(row=1, column=4, sticky="w", **pad)
        self._help(ov, 2, "Or just drag the box to where you want it once it opens.")

        # poker options
        self.pf = ttk.LabelFrame(body, text="Poker options")
        self.pf.grid(row=2, column=0, sticky="ew", **pad)
        ttk.Checkbutton(self.pf, text="Auto-detect my hole cards",
                        variable=self.v["detect"]).grid(row=0, column=0, columnspan=4, sticky="w", **pad)
        self._help(self.pf, 1, "Reads your 2 cards; press Enter to confirm or type to fix a wrong one.")
        ttk.Checkbutton(self.pf, text="Learn from my corrections",
                        variable=self.v["learn"]).grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        self._help(self.pf, 3, "Each confirmed/corrected hand is saved so detection keeps improving.")
        ttk.Label(self.pf, text="Opponents at the table").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(self.pf, textvariable=self.v["opp"], width=5).grid(row=4, column=1, sticky="w")
        self._help(self.pf, 5, "Fallback only - used when it can't count the active players itself.")
        ttk.Label(self.pf, text="Odds simulation runs").grid(row=6, column=0, sticky="w", **pad)
        ttk.Entry(self.pf, textvariable=self.v["iters"], width=8).grid(row=6, column=1, sticky="w")
        self._help(self.pf, 7, "Random deals run to estimate your win % - more = steadier odds, "
                               "a bit slower (default 12000).")
        ttk.Label(self.pf, text="Confirm hotkey").grid(row=8, column=0, sticky="w", **pad)
        ttk.Entry(self.pf, textvariable=self.v["confirm_key"], width=8).grid(row=8, column=1, sticky="w")
        self._help(self.pf, 9, "Global key that confirms the hand (= Enter). Map a Steam "
                               "controller back button to it. f13-f24/home/end/... ; blank = off.")
        ttk.Label(self.pf, text="Card reader").grid(row=10, column=0, sticky="w", **pad)
        rf = ttk.Frame(self.pf)
        rf.grid(row=10, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(rf, text="HOG (learns as you play)", value="HOG",
                        variable=self.v["reader"]).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(rf, text="CNN (stronger, fixed)", value="CNN",
                        variable=self.v["reader"]).grid(row=0, column=1, sticky="w", padx=8)
        self._help(self.pf, 11, "HOG retrains instantly on your corrections. CNN reads better "
                                "(incl. obscured cards) but is fixed until retrained, and needs the "
                                "trained model file (models/cnn_card.pt).")

        # blackjack options
        self.bf = ttk.LabelFrame(body, text="Blackjack options")
        self.bf.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Label(self.bf, text="Decks in the shoe").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self.bf, textvariable=self.v["decks"], width=5).grid(row=0, column=1, sticky="w", **pad)
        ttk.Checkbutton(self.bf, text="Hi-Lo card counting",
                        variable=self.v["count"]).grid(row=1, column=0, columnspan=4, sticky="w", **pad)
        self._help(self.bf, 2, "Experimental - multi-seat table, the count can't see most cards (off by default).")
        ttk.Checkbutton(self.bf, text="Save each hand to a database",
                        variable=self.v["db"]).grid(row=3, column=0, columnspan=4, sticky="w", **pad)
        self._help(self.bf, 4, "Logs results to data/sessions for later review.")
        ttk.Label(self.bf, text="Also write a CSV log").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(self.bf, textvariable=self.v["log"], width=22).grid(row=5, column=1, columnspan=2, sticky="ew", **pad)
        self._help(self.bf, 6, "Optional - leave blank to skip; e.g. hands.csv.")

        # advanced / rarely-changed settings
        adv = ttk.LabelFrame(body, text="Advanced (defaults are usually fine)")
        adv.grid(row=4, column=0, sticky="ew", **pad)
        ttk.Label(adv, text="Re-read the screen every").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(adv, textvariable=self.v["interval"], width=5).grid(row=0, column=1, sticky="w")
        ttk.Label(adv, text="seconds").grid(row=0, column=2, sticky="w", **pad)
        ttk.Label(adv, text="Match confidence").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(adv, textvariable=self.v["min_confidence"], width=5).grid(row=1, column=1, sticky="w")
        self._help(adv, 2, "0-1; lower reads more but misreads more. Leave at 0.6 unless reads are flaky.")
        ttk.Label(adv, text="Calibration file").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(adv, textvariable=self.v["config"], width=24).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(adv, text="Browse...", command=self._browse_config).grid(row=3, column=3, **pad)
        self._help(adv, 4, "The screen regions from the one-time calibration step (regions.json).")

        # command preview + status
        self.preview = tk.Text(body, height=5, width=52, wrap="word",
                               bg="#101010", fg="#39ff14", font=("Consolas", 9))
        self.preview.grid(row=5, column=0, sticky="ew", **pad)
        self.preview.configure(state="disabled")
        self.status = ttk.Label(body, text="", foreground="#a00")
        self.status.grid(row=6, column=0, sticky="w", **pad)

        bf = ttk.Frame(body)
        bf.grid(row=7, column=0, sticky="ew", **pad)
        ttk.Button(bf, text="Launch overlay", command=self.on_launch).grid(row=0, column=0, **pad)
        ttk.Button(bf, text="Stop overlay", command=self.on_stop).grid(row=0, column=1, **pad)
        ttk.Button(bf, text="Quit", command=self.on_quit).grid(row=0, column=2, **pad)

        # in-process poker session + correction panel (built once, shown while running)
        self._sess = None
        self._pollers = set()        # confirm-hotkey VKs already being polled
        self.corr_mode = tk.StringVar(value="dropdown")
        self._build_corrections(body, row=8)

        # log pane: session output (learning, errors) instead of a console
        lf = ttk.LabelFrame(body, text="Log")
        lf.grid(row=9, column=0, sticky="ew", **pad)
        self.log = tk.Text(lf, height=6, width=52, wrap="word", bg="#0a0a0a",
                           fg="#cccccc", font=("Consolas", 8), state="disabled")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)
        self._orig_stdout = None

        self.labels = LabelsTab(self.tab_labels, tk, ttk, root, ROOT,
                                lambda: self._sess, self._labels_config_path)

        self.v["game"].trace_add("write", lambda *_: self._toggle())
        self.corr_mode.trace_add("write", lambda *_: self._show_corr_mode())
        root.protocol("WM_DELETE_WINDOW", self.on_quit)   # X button closes overlays too
        self._install_confirm_hotkey(DEFAULTS["confirm_key"])   # paddle works for review too
        self._toggle()
        self._refresh()

    def _install_confirm_hotkey(self, confirm_key):
        """Poll the global confirm key (e.g. an R4 paddle mapped to Insert) for the
        launcher's life. Installed once; reused across sessions (the _pollers guard
        stops duplicates). Windows-only."""
        if os.name != "nt" or not confirm_key:
            return
        from .live import _key_poller, _VK
        vk = _VK.get(str(confirm_key).lower())
        if vk is not None and vk not in self._pollers:
            self._pollers.add(vk)
            _key_poller(self.root, vk, self._on_confirm_key)

    def _on_confirm_key(self):
        """The confirm hotkey acts on the tab you're viewing: confirm the poker hand
        on the Play tab, or mark-reviewed + jump to the next crop on the Labels tab."""
        try:
            on_labels = str(self.nb.select()) == str(self.tab_labels)
        except Exception:                              # noqa: BLE001
            on_labels = False
        (self.labels.confirm_and_next if on_labels else self._confirm_hotkey)()

    def _labels_config_path(self):
        """Resolved regions.json path for the Labels tab's capture/import."""
        return str(ROOT / (self.v["config"].get().strip() or "config/regions.json"))

    def _help(self, parent, row, text, col=0, colspan=5):
        """A small grey hint line under a control."""
        self.ttk.Label(parent, text=text, foreground="#888",
                       font=("Segoe UI", 8)).grid(row=row, column=col, columnspan=colspan,
                                                   sticky="w", padx=8)

    def _browse_config(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(
            title="Calibration file", initialdir=str(ROOT),
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if p:
            try:
                p = os.path.relpath(p, ROOT)
            except ValueError:
                pass
            self.v["config"].set(p)

    def _toggle(self):
        """Show only the selected game's options."""
        poker = self.v["game"].get() == "poker"
        (self.pf.grid if poker else self.pf.grid_remove)()
        (self.bf.grid_remove if poker else self.bf.grid)()

    def _options(self):
        """Current form values as a plain dict (numbers parsed; raises ValueError)."""
        g = self.v["game"].get()
        return {
            "game": g,
            "config": self.v["config"].get().strip() or DEFAULTS["config"],
            "interval": float(self.v["interval"].get()),
            "min_confidence": float(self.v["min_confidence"].get()),
            "x": int(self.v["x"].get()),
            "y": int(self.v["y"].get()),
            "overlay": self.v["overlay"].get(),
            "detect": self.v["detect"].get(),
            "reader": self.v["reader"].get(),
            "learn": self.v["learn"].get(),
            "confirm_key": self.v["confirm_key"].get().strip(),
            "opp": int(self.v["opp"].get()),
            "iters": int(self.v["iters"].get()),
            "decks": int(self.v["decks"].get()),
            "count": self.v["count"].get(),
            "db": self.v["db"].get(),
            "log": self.v["log"].get().strip(),
        }

    def _refresh(self, *_):
        """Update the command preview + a calibration/path warning."""
        try:
            o = self._options()
            text = (summarize(o) + "\n\nruns:  python -m judgment_assist.app.live "
                    + " ".join(build_argv(o)))
            warn = "" if (ROOT / o["config"]).exists() else \
                "config not found - run calibration (mark) first"
        except ValueError:
            text, warn = "(enter valid numbers above)", ""
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")
        self.status.configure(text=warn)

    def on_launch(self):
        from tkinter import messagebox
        if self._sess is not None or any(p.poll() is None for p in self.procs):
            self.status.configure(text="already running - Stop it first", foreground="#a00")
            return
        try:
            o = self._options()
        except ValueError:
            messagebox.showerror("Invalid", "Interval, confidence, positions and "
                                 "counts must be numbers.")
            return
        if not (ROOT / o["config"]).exists():
            self.status.configure(text="config not found - run calibration first",
                                  foreground="#a00")
            return
        if o["game"] == "poker":
            self._start_poker(o)        # in-process: overlay + corrections in the launcher
        else:
            proc = launch(build_argv(o))   # blackjack stays a separate process
            self.procs.append(proc)
            self.status.configure(text=f"overlay running (PID {proc.pid})", foreground="#070")
            self._watch(proc)

    def _watch(self, proc):
        """Poll the launched overlay and update the status when it stops (closed,
        or exited early if it failed to start) — but only if it's still the latest."""
        if proc.poll() is None:
            self.root.after(1000, lambda: self._watch(proc))
            return
        if not (self.procs and self.procs[-1] is proc):
            return                                    # a newer overlay was launched
        code = proc.returncode
        ok = code in (0, None)
        if code == 3:                                 # OVERLAY_BUSY_EXIT from app.live
            msg = "an overlay is already running (close the other one)"
        elif ok:
            msg = "overlay stopped"
        else:
            msg = f"overlay exited early (code {code})"
        try:
            self.status.configure(text=msg, foreground="#070" if ok else "#a00")
        except Exception:
            pass

    def on_stop(self):
        if self._sess is not None:                # in-process poker session
            self._stop_session()
            self.status.configure(text="overlay stopped", foreground="#070")
            return
        live = [p for p in self.procs if p.poll() is None]
        if not live:
            self.status.configure(text="nothing running", foreground="#a00")
            return
        p = live[-1]
        p.terminate()
        self.status.configure(text=f"stopped PID {p.pid}", foreground="#070")

    def on_quit(self):
        """Close the launcher and any overlays it started (don't leave them
        running headless)."""
        self._stop_session()
        terminate_all(self.procs)
        self.root.destroy()

    # ----------------------------------------------- in-process poker session --
    def _start_poker(self, o):
        from .live import (load_config, grab_frame, _screen_dimmed, _key_poller,
                           _VK, PokerAdvisor)
        from .overlay import SuggestionOverlay
        from ..vision.hud import HudReader
        from ..capture.screen import ScreenGrabber
        try:
            cfg = load_config(str(ROOT / o["config"]))
            roi = cfg.get("poker")
            if not roi:
                raise RuntimeError("no 'poker' section in the config (calibrate first)")
            reader = HudReader(str(ROOT / "data" / "poker_digits"),
                               min_confidence=o["min_confidence"])
        except Exception as e:                    # noqa: BLE001
            self.status.configure(text=f"can't start: {e}", foreground="#a00")
            return
        card_reader = training = None
        if o["detect"]:
            cards_dir = ROOT / "data" / "poker_cards"
            if o.get("reader") == "CNN":
                ckpt = ROOT / "models" / "cnn_card.pt"
                try:
                    if not ckpt.exists():
                        raise FileNotFoundError("no trained CNN model (models/cnn_card.pt)")
                    from ..vision.cnn_cards import CnnCardReader     # lazy: torch only here
                    card_reader = CnnCardReader(str(ckpt))
                    print("card reader: CNN (ResNet34) — fixed model, corrections bank for retrain")
                except Exception as e:                # noqa: BLE001 - fall back to HOG
                    print(f"  (CNN reader unavailable — {e}; using HOG)")
            if card_reader is None:
                try:
                    from ..vision.poker_cards import HoleCardReader
                    card_reader = HoleCardReader(str(cards_dir))
                except RuntimeError:
                    pass
        if o["learn"]:
            try:
                from ..vision.poker_cards import TrainingWriter
                training = TrainingWriter(str(ROOT / "data" / "poker_cards"))
            except RuntimeError:
                pass
        advisor = PokerAdvisor(reader, roi, opp_fallback=o["opp"], iters=o["iters"],
                               card_reader=card_reader, training=training)
        self.labels.on_session_start()    # read this fresh advisor's bank log from the top
        grab = ScreenGrabber(monitor=cfg.get("monitor", 1))
        grab.__enter__()
        overlay = SuggestionOverlay(master=self.root, input_enabled=False,
                                    x=o["x"], y=o["y"])
        overlay.root.protocol("WM_DELETE_WINDOW", self.on_stop)   # X stops the session
        self._sess = {"advisor": advisor, "grab": grab, "overlay": overlay, "cfg": cfg,
                      "last": None, "interval": max(60, int(o["interval"] * 1000)),
                      "running": True, "grab_frame": grab_frame, "dim": _screen_dimmed}
        if os.name == "nt" and o["confirm_key"]:
            vk = _VK.get(o["confirm_key"].lower())
            if vk and vk not in self._pollers:       # one poller per key, reused across sessions
                self._pollers.add(vk)
                _key_poller(self.root, vk, self._on_confirm_key)
        self.cf2.grid(row=self._corr_row, column=0, sticky="ew", padx=8, pady=3)
        self._show_corr_mode()
        self.status.configure(text="overlay running (corrections below)", foreground="#070")
        self._orig_stdout = sys.stdout              # capture session output into the Log pane
        sys.stdout = _GuiWriter(self.log, self._orig_stdout)
        print(f"session started - detect {'on' if card_reader else 'off'}, "
              f"learn {'on' if training else 'off'}")
        self._tick()

    def _confirm_hotkey(self):
        from ..cards import cards_str
        if not self._sess:
            self.status.configure(text="confirm: no overlay running - Launch first",
                                  foreground="#a00")
            return
        adv = self._sess["advisor"]
        adv.confirm()
        if len(adv.hole) == 2:
            msg = f"confirmed {cards_str(adv.hole)}"
            if adv.board:
                msg += " | " + cards_str(adv.board)
            self.status.configure(text=msg + "  (banked for training)", foreground="#070")
        else:
            self.status.configure(text="confirm: no hand detected yet", foreground="#a00")

    def _tick(self):
        s = self._sess
        if not s or not s["running"]:
            return
        # A throw anywhere below used to skip the reschedule and FREEZE the overlay
        # (e.g. it got stuck on "reading the board" if a card read raised). Guard the
        # whole frame and always reschedule, so one bad frame just gets retried.
        frame = None
        try:
            frame = s["grab_frame"](s["grab"], s["cfg"])
            if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
                text = "poker: 'Judgment' window not found - open it on the poker table"
            elif s["dim"](frame):
                text = "== PAUSED ==  (resume the game)" + (f"\n\n{s['last']}" if s["last"] else "")
            else:
                text = s["advisor"].text(frame)
                s["last"] = text
            s["overlay"].update_text(text)
            self._refresh_corrections()
            self.labels.append_live_banks()
        except Exception as e:                    # noqa: BLE001 - keep the loop alive
            import traceback
            tb = traceback.format_exc()
            print(f"  tick error (recovered, retrying): {e}")
            print(tb)
            # Persist the traceback AND the offending full-res frame so an
            # intermittent, data-specific read crash can be reproduced exactly
            # later (the Log pane isn't on disk). Best-effort; never re-raises.
            _save_tick_error(tb, frame)
            try:
                s["overlay"].update_text((s.get("last") or "(reading...)")
                                         + f"\n(read hiccup: {e})")
            except Exception:                     # noqa: BLE001
                pass
        finally:
            if s.get("running"):
                self.root.after(s["interval"], self._tick)

    def _stop_session(self):
        s = self._sess
        if not s:
            return
        s["running"] = False
        try:
            s["grab"].__exit__(None, None, None)
        except Exception:
            pass
        try:
            s["overlay"].close()
        except Exception:
            pass
        if self._orig_stdout is not None:           # restore stdout
            sys.stdout = self._orig_stdout
            self._orig_stdout = None
        self.cf2.grid_remove()
        self._sess = None

    # ---------------------------------------------------- corrections panel ----
    _SLOTS = [("H", 0), ("H", 1), ("B", 0), ("B", 1), ("B", 2), ("B", 3), ("B", 4)]
    _RANKS = list("23456789TJQKA")
    _SUITS = ["c", "d", "h", "s"]

    def _slot_label(self, kind, idx):
        return (f"Hole {idx + 1}" if kind == "H" else f"Board {idx + 1}")

    def _build_corrections(self, root, row):
        tk, ttk = self.tk, self.ttk
        self._corr_row = row
        self.cf2 = ttk.LabelFrame(root, text="Corrections - fix any wrong card (no typing)")
        mt = ttk.Frame(self.cf2)
        mt.grid(row=0, column=0, sticky="w", padx=8, pady=2)
        ttk.Label(mt, text="Style:").grid(row=0, column=0)
        ttk.Radiobutton(mt, text="Dropdowns", value="dropdown",
                        variable=self.corr_mode).grid(row=0, column=1, padx=4)
        ttk.Radiobutton(mt, text="Card grid", value="grid",
                        variable=self.corr_mode).grid(row=0, column=2)
        ttk.Button(mt, text="✓ Confirm hand (all correct)",
                   command=self._confirm_hotkey).grid(row=0, column=3, padx=16)
        ttk.Label(mt, text="(or your R4 / Insert button)", foreground="#888",
                  font=("Segoe UI", 8)).grid(row=0, column=4)

        self.dd = ttk.Frame(self.cf2)        # dropdown style
        self.grd = ttk.Frame(self.cf2)       # card-grid style
        self._cells = []
        for col, (kind, idx) in enumerate(self._SLOTS):
            cell = ttk.Frame(self.dd)
            cell.grid(row=0, column=col, padx=3, pady=2)
            ttk.Label(cell, text=self._slot_label(kind, idx),
                      font=("Segoe UI", 8)).grid(row=0, column=0, columnspan=2)
            rv, sv = tk.StringVar(), tk.StringVar()
            rc = ttk.Combobox(cell, values=self._RANKS, textvariable=rv, width=3, state="disabled")
            sc = ttk.Combobox(cell, values=self._SUITS, textvariable=sv, width=3, state="disabled")
            rc.grid(row=1, column=0)
            sc.grid(row=1, column=1)
            i = len(self._cells)
            rc.bind("<<ComboboxSelected>>", lambda e, i=i: self._pick(i))
            sc.bind("<<ComboboxSelected>>", lambda e, i=i: self._pick(i))
            self._cells.append({"kind": kind, "idx": idx, "rank": rv, "suit": sv, "rc": rc, "sc": sc})

        self._sel = 0                        # selected slot for the grid style
        self._slotbtns = []
        sb = ttk.Frame(self.grd)
        sb.grid(row=0, column=0, sticky="w", pady=(2, 4))
        for col, (kind, idx) in enumerate(self._SLOTS):
            b = ttk.Button(sb, text="-", width=9, command=lambda i=col: self._grid_select(i))
            b.grid(row=0, column=col, padx=2)
            self._slotbtns.append(b)
        rk = ttk.Frame(self.grd)
        rk.grid(row=1, column=0, sticky="w")
        ttk.Label(rk, text="rank:").grid(row=0, column=0)
        for c, r in enumerate(self._RANKS):
            ttk.Button(rk, text=r, width=2,
                       command=lambda r=r: self._grid_set("rank", r)).grid(row=0, column=c + 1)
        su = ttk.Frame(self.grd)
        su.grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(su, text="suit:").grid(row=0, column=0)
        for c, s in enumerate(self._SUITS):
            ttk.Button(su, text=s, width=2,
                       command=lambda s=s: self._grid_set("suit", s)).grid(row=0, column=c + 1)
        self._grid_hint = ttk.Label(self.grd, text="pick a slot, then a rank + suit",
                                    foreground="#888", font=("Segoe UI", 8))
        self._grid_hint.grid(row=3, column=0, sticky="w", pady=2)

    def _show_corr_mode(self):
        if self.corr_mode.get() == "grid":
            self.dd.grid_remove()
            self.grd.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        else:
            self.grd.grid_remove()
            self.dd.grid(row=1, column=0, sticky="w", padx=8, pady=4)

    def _grid_select(self, i):
        self._sel = i
        kind, idx = self._SLOTS[i]
        self._grid_hint.configure(text=f"editing {self._slot_label(kind, idx)} - pick a rank + suit")

    def _grid_set(self, field, val):
        self._cells[self._sel][field].set(val)
        self._pick(self._sel)

    def _pick(self, i):
        """Apply ONE picked card: update the hand state (full group, for equity) but
        bank only the single card the hero changed — not the rest of the hand."""
        from ..cards import parse_card, cards_str
        if not self._sess:
            return
        cell = self._cells[i]
        kind, idx = cell["kind"], cell["idx"]
        if not (cell["rank"].get() and cell["suit"].get()):
            return
        changed = parse_card(cell["rank"].get() + cell["suit"].get())
        group = [parse_card(c["rank"].get() + c["suit"].get()) for c in self._cells
                 if c["kind"] == kind and c["rank"].get() and c["suit"].get()]
        adv = self._sess["advisor"]
        if kind == "H" and len(group) == 2:
            adv.set_hole(group)
        elif kind == "B" and group:
            adv.set_board(group)
        else:
            return
        adv.bank_card(kind, idx, changed)        # bank ONLY the card you changed
        where = "hole" if kind == "H" else "board"
        self.status.configure(text=f"corrected {where} card {idx + 1} to "
                              f"{cards_str([changed])}", foreground="#070")

    def _refresh_corrections(self):
        from ..cards import INT_TO_RANK, INT_TO_SUIT
        s = self._sess
        if not s:
            return
        adv = s["advisor"]
        hole, board = list(adv.hole), list(adv.board)
        # Board slots are editable up to the number of community cards ON SCREEN, not
        # just the ones detection filled — so a slot the reader can't read is still
        # correctable (that un-sticks "reading the board"). Hole stays gated on a
        # detected card.
        screen_board = getattr(adv, "screen_board", 0)
        for i, cell in enumerate(self._cells):
            if cell["kind"] == "H":
                card = hole[cell["idx"]] if cell["idx"] < len(hole) else None
                fixed = adv.hole_locked
                editable = card is not None
            else:
                card = board[cell["idx"]] if cell["idx"] < len(board) else None
                fixed = cell["idx"] in adv._board_fixed
                editable = cell["idx"] < max(len(board), screen_board)
            cell["rc"].configure(state="readonly" if editable else "disabled")
            cell["sc"].configure(state="readonly" if editable else "disabled")
            if card is not None and not fixed:   # reflect detection (don't fight a typed fix)
                cell["rank"].set(INT_TO_RANK[card[0]])
                cell["suit"].set(INT_TO_SUIT[card[1]])
            elif not editable:                   # empty + not on screen -> clear; an
                cell["rank"].set("")             # editable-but-empty slot is the user's
                cell["suit"].set("")             # to fill, so leave it alone
            lab = ("H" if cell["kind"] == "H" else "B") + str(cell["idx"] + 1)
            txt = (INT_TO_RANK[card[0]] + INT_TO_SUIT[card[1]]) if card is not None else "-"
            self._slotbtns[i].configure(text=f"{lab}:{txt}")

_MUTEX_NAME = "rgg-advisor-launcher"


def acquire_single_instance(name=_MUTEX_NAME):
    """Return a lock handle, or None if a launcher is already running. Uses a named
    mutex on Windows (no deps); a no-op elsewhere. Keep the returned handle alive
    for the process lifetime — the OS frees the mutex when the process exits."""
    if os.name != "nt":
        return True
    import ctypes
    k = ctypes.windll.kernel32
    handle = k.CreateMutexW(None, False, name)
    if k.GetLastError() == 183:        # ERROR_ALREADY_EXISTS -> another instance
        if handle:
            k.CloseHandle(handle)
        return None
    return handle


def main():
    import tkinter as tk
    lock = acquire_single_instance()
    if lock is None:                   # only one launcher at a time
        root = tk.Tk()
        root.withdraw()
        try:
            from tkinter import messagebox
            messagebox.showinfo("RGG advisor launcher",
                                "The launcher is already running.")
        finally:
            root.destroy()
        return
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
