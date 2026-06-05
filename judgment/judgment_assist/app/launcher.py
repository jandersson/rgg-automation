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
    "y": 40,
    "overlay": True,        # False -> --no-overlay (console only)
    # poker
    "detect": True,         # False -> --no-detect
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

        self.v = {
            "game": tk.StringVar(value=DEFAULTS["game"]),
            "config": tk.StringVar(value=DEFAULTS["config"]),
            "interval": tk.StringVar(value=str(DEFAULTS["interval"])),
            "min_confidence": tk.StringVar(value=str(DEFAULTS["min_confidence"])),
            "x": tk.StringVar(value=str(DEFAULTS["x"])),
            "y": tk.StringVar(value=str(DEFAULTS["y"])),
            "overlay": tk.BooleanVar(value=DEFAULTS["overlay"]),
            "detect": tk.BooleanVar(value=DEFAULTS["detect"]),
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
        # game selector
        gf = ttk.LabelFrame(root, text="Game")
        gf.grid(row=0, column=0, sticky="ew", **pad)
        for i, g in enumerate(("poker", "blackjack")):
            ttk.Radiobutton(gf, text=g.capitalize(), value=g,
                            variable=self.v["game"]).grid(row=0, column=i, sticky="w", **pad)
        self._help(gf, 1, "Poker = Hold'em equity + pot-odds.   Blackjack = basic-strategy advice.",
                   colspan=3)

        # the overlay (one window: advice + the card-entry box)
        ov = ttk.LabelFrame(root, text="Overlay")
        ov.grid(row=1, column=0, sticky="ew", **pad)
        self._help(ov, 0, "A floating box over the game shows the advice and (poker) "
                          "takes your card entry - all in one window.")
        ttk.Label(ov, text="Position:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(ov, textvariable=self.v["x"], width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(ov, text="across,").grid(row=1, column=2, sticky="w")
        ttk.Entry(ov, textvariable=self.v["y"], width=5).grid(row=1, column=3, sticky="w")
        ttk.Label(ov, text="down  (pixels from the top-left)").grid(row=1, column=4, sticky="w", **pad)
        self._help(ov, 2, "Or just drag the box to where you want it once it opens.")

        # poker options
        self.pf = ttk.LabelFrame(root, text="Poker options")
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

        # blackjack options
        self.bf = ttk.LabelFrame(root, text="Blackjack options")
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
        adv = ttk.LabelFrame(root, text="Advanced (defaults are usually fine)")
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
        self.preview = tk.Text(root, height=5, width=52, wrap="word",
                               bg="#101010", fg="#39ff14", font=("Consolas", 9))
        self.preview.grid(row=5, column=0, sticky="ew", **pad)
        self.preview.configure(state="disabled")
        self.status = ttk.Label(root, text="", foreground="#a00")
        self.status.grid(row=6, column=0, sticky="w", **pad)

        bf = ttk.Frame(root)
        bf.grid(row=7, column=0, sticky="ew", **pad)
        ttk.Button(bf, text="Launch overlay", command=self.on_launch).grid(row=0, column=0, **pad)
        ttk.Button(bf, text="Stop overlay", command=self.on_stop).grid(row=0, column=1, **pad)
        ttk.Button(bf, text="Quit", command=self.on_quit).grid(row=0, column=2, **pad)

        self.v["game"].trace_add("write", lambda *_: self._toggle())
        root.protocol("WM_DELETE_WINDOW", self.on_quit)   # X button closes overlays too
        self._toggle()
        self._refresh()

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
        if any(p.poll() is None for p in self.procs):    # one overlay at a time
            self.status.configure(text="an overlay is already running - Stop it first",
                                  foreground="#a00")
            return
        try:
            argv = build_argv(self._options())
        except ValueError:
            messagebox.showerror("Invalid", "Interval, confidence, positions and "
                                 "counts must be numbers.")
            return
        proc = launch(argv)
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
        terminate_all(self.procs)
        self.root.destroy()


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
