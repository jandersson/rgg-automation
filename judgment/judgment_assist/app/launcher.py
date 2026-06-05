"""GUI launcher for the live overlays — pick the game, set the flags, launch.

    uv run python -m judgment_assist.app.launcher

A small tkinter form (no extra deps, same toolkit as the overlay) over
``app.live``'s flags. It spawns the advisor in its own console window so the
poker card-entry prompt has a terminal and you can Ctrl-C / read logs, while the
always-on-top overlay floats over the game. The launcher stays open so you can
tweak and relaunch.

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
    "opp": 2,
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
    """Spawn ``app.live`` with ``argv`` in a new console window (Windows) so the
    poker prompt has stdin and logs are visible. Returns the Popen handle."""
    cmd = [sys.executable, "-m", "judgment_assist.app.live", *argv]
    kwargs = {"cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
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
                            variable=self.v["game"]).grid(row=0, column=i, **pad)

        # common settings
        cf = ttk.LabelFrame(root, text="Overlay & capture")
        cf.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Checkbutton(cf, text="Show overlay (uncheck = console only)",
                        variable=self.v["overlay"]).grid(row=0, column=0, columnspan=4, sticky="w", **pad)
        self._row(cf, 1, "Overlay X (from left)", "x", 6, "Y (from top)", "y", 6)
        self._row(cf, 2, "Interval (s)", "interval", 6, "Min confidence", "min_confidence", 6)
        ttk.Label(cf, text="Config").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(cf, textvariable=self.v["config"], width=34).grid(row=3, column=1, columnspan=3, sticky="ew", **pad)

        # poker box
        self.pf = ttk.LabelFrame(root, text="Poker")
        self.pf.grid(row=2, column=0, sticky="ew", **pad)
        ttk.Checkbutton(self.pf, text="Auto-detect hole cards (correct by typing)",
                        variable=self.v["detect"]).grid(row=0, column=0, columnspan=4, sticky="w", **pad)
        ttk.Checkbutton(self.pf, text="Learn: save confirmed/corrected cards as training data",
                        variable=self.v["learn"]).grid(row=1, column=0, columnspan=4, sticky="w", **pad)
        self._row(self.pf, 2, "Opponents (fallback)", "opp", 6, "Equity iters", "iters", 8)

        # blackjack box
        self.bf = ttk.LabelFrame(root, text="Blackjack")
        self.bf.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Label(self.bf, text="Decks").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self.bf, textvariable=self.v["decks"], width=6).grid(row=0, column=1, sticky="w", **pad)
        ttk.Checkbutton(self.bf, text="Hi-Lo counting (experimental)",
                        variable=self.v["count"]).grid(row=1, column=0, columnspan=4, sticky="w", **pad)
        ttk.Checkbutton(self.bf, text="Session DB logging",
                        variable=self.v["db"]).grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        ttk.Label(self.bf, text="Log CSV (optional)").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(self.bf, textvariable=self.v["log"], width=28).grid(row=3, column=1, columnspan=3, sticky="ew", **pad)

        # command preview + status
        self.preview = tk.Text(root, height=5, width=52, wrap="word",
                               bg="#101010", fg="#39ff14", font=("Consolas", 9))
        self.preview.grid(row=4, column=0, sticky="ew", **pad)
        self.preview.configure(state="disabled")
        self.status = ttk.Label(root, text="", foreground="#a00")
        self.status.grid(row=5, column=0, sticky="w", **pad)

        bf = ttk.Frame(root)
        bf.grid(row=6, column=0, sticky="ew", **pad)
        ttk.Button(bf, text="Launch overlay", command=self.on_launch).grid(row=0, column=0, **pad)
        ttk.Button(bf, text="Stop overlay", command=self.on_stop).grid(row=0, column=1, **pad)
        ttk.Button(bf, text="Quit", command=self.on_quit).grid(row=0, column=2, **pad)

        self.v["game"].trace_add("write", lambda *_: self._toggle())
        root.protocol("WM_DELETE_WINDOW", self.on_quit)   # X button closes overlays too
        self._toggle()
        self._refresh()

    def _row(self, parent, r, l1, k1, w1, l2, k2, w2):
        self.ttk.Label(parent, text=l1).grid(row=r, column=0, sticky="w", padx=8, pady=3)
        self.ttk.Entry(parent, textvariable=self.v[k1], width=w1).grid(row=r, column=1, sticky="w", padx=8, pady=3)
        self.ttk.Label(parent, text=l2).grid(row=r, column=2, sticky="w", padx=8, pady=3)
        self.ttk.Entry(parent, textvariable=self.v[k2], width=w2).grid(row=r, column=3, sticky="w", padx=8, pady=3)

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
        try:
            argv = build_argv(self._options())
        except ValueError:
            messagebox.showerror("Invalid", "Interval, confidence, positions and "
                                 "counts must be numbers.")
            return
        proc = launch(argv)
        self.procs.append(proc)
        self.status.configure(text=f"launched (PID {proc.pid}) in a new console",
                              foreground="#070")

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


def main():
    import tkinter as tk
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
