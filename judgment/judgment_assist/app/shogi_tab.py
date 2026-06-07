"""The launcher's Shogi tab.

Shogi has no screen-reading yet (that's the roadmap), so unlike the poker/blackjack
overlays this is a *typed* advisor: paste a position (SFEN), optionally play some
moves, and get the best move — an exact forced mate from the pure-Python solver,
or the USI engine's pick for a positional call.

The non-tk logic (``build_state``, ``format_advice``, ``load_engine_config``) is
module-level and pure so it can be unit-tested without a display or an engine. The
``ShogiTab`` class is the thin tkinter shell; engine calls run on a worker thread
so a ~1s think never freezes the launcher.
"""
from __future__ import annotations

import json
import threading

from ..shogi.board import ShogiState, START_SFEN
from ..shogi.engine import UsiEngine, best_move

DEFAULT_MOVETIME = 1000      # ms the engine thinks per move
DEFAULT_MATE_MOVES = 7       # max forced-mate depth (attacker moves)


def load_engine_config(root_dir):
    """Read ``config/shogi.json`` -> ``(engine_path, usi_options, movetime)``.
    Missing/garbled config is fine — returns sensible blanks."""
    try:
        with open(root_dir / "config" / "shogi.json", encoding="utf-8") as f:
            cfg = json.load(f)
        return (cfg.get("engine") or "",
                cfg.get("usi_options", {}) or {},
                int(cfg.get("movetime", DEFAULT_MOVETIME)))
    except (FileNotFoundError, ValueError, TypeError):
        return "", {}, DEFAULT_MOVETIME


def build_state(sfen, moves):
    """``(state, error)`` from an SFEN string (blank = opening) plus space/comma
    separated USI moves to play from it. ``error`` is a message, or None."""
    sfen = (sfen or "").strip()
    try:
        state = ShogiState(sfen) if sfen else ShogiState()
    except Exception as e:                       # noqa: BLE001 - surface to the UI
        return None, f"bad SFEN: {e}"
    for mv in (moves or "").replace(",", " ").split():
        try:
            state.push_usi(mv)
        except ValueError as e:
            return None, str(e)
    return state, None


def format_advice(out):
    """One/two-line recommendation from a :func:`best_move` result dict."""
    src = out.get("source")
    if src == "mate":
        return (f"BEST:  {out['move']}     (forced mate in {out['mate_in']})\n"
                f"line:  {' '.join(out['pv'])}")
    if src == "engine":
        return f"BEST:  {out['move']}     (engine)"
    return out.get("note", "no advice available")


class ShogiTab:
    def __init__(self, parent, tk, ttk, root, root_dir):
        self.tk, self.ttk, self.root = tk, ttk, root
        self._root_dir = root_dir
        self._engine = None
        self._engine_started_for = None          # path the live engine was started with
        self._gen = 0                            # ignore results from superseded clicks
        cfg_path, cfg_opts, cfg_movetime = load_engine_config(root_dir)
        self._engine_options = cfg_opts
        self._build(parent, cfg_path, cfg_movetime)

    # ----------------------------------------------------------------- build ---
    def _build(self, parent, cfg_path, cfg_movetime):
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 8, "pady": 3}
        parent.columnconfigure(0, weight=1)

        ttk.Label(parent, text="Type a position (SFEN) and optional moves, then Advise. "
                  "Forced mates are solved exactly with no engine; positional calls use "
                  "the USI engine.", foreground="#555", font=("Segoe UI", 9),
                  wraplength=520).grid(row=0, column=0, sticky="w", **pad)

        pos = ttk.LabelFrame(parent, text="Position")
        pos.grid(row=1, column=0, sticky="ew", **pad)
        pos.columnconfigure(1, weight=1)
        ttk.Label(pos, text="SFEN").grid(row=0, column=0, sticky="w", **pad)
        self.sfen = tk.StringVar(value=START_SFEN)
        ttk.Entry(pos, textvariable=self.sfen).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(pos, text="Opening", command=lambda: self.sfen.set(START_SFEN)
                   ).grid(row=0, column=2, **pad)
        ttk.Label(pos, text="Moves").grid(row=1, column=0, sticky="w", **pad)
        self.moves = tk.StringVar(value="")
        ttk.Entry(pos, textvariable=self.moves).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(pos, text="Clear", command=lambda: self.moves.set("")
                   ).grid(row=1, column=2, **pad)
        ttk.Label(pos, text="USI moves to play from the SFEN, e.g. '7g7f 3c3d' (drops like G*5b)",
                  foreground="#888", font=("Segoe UI", 8)).grid(row=2, column=1, sticky="w", padx=8)

        eng = ttk.LabelFrame(parent, text="Engine")
        eng.grid(row=2, column=0, sticky="ew", **pad)
        eng.columnconfigure(1, weight=1)
        self.use_engine = tk.BooleanVar(value=bool(cfg_path))
        ttk.Checkbutton(eng, text="Use USI engine for positional advice",
                        variable=self.use_engine).grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(eng, text="Engine").grid(row=1, column=0, sticky="w", **pad)
        self.engine_path = tk.StringVar(value=cfg_path)
        ttk.Entry(eng, textvariable=self.engine_path).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(eng, text="Browse...", command=self._browse_engine).grid(row=1, column=2, **pad)
        opt = ttk.Frame(eng)
        opt.grid(row=2, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Label(opt, text="Think (ms)").grid(row=0, column=0, **pad)
        self.movetime = tk.StringVar(value=str(cfg_movetime))
        ttk.Entry(opt, textvariable=self.movetime, width=7).grid(row=0, column=1)
        ttk.Label(opt, text="Max mate depth").grid(row=0, column=2, **pad)
        self.mate_moves = tk.StringVar(value=str(DEFAULT_MATE_MOVES))
        ttk.Entry(opt, textvariable=self.mate_moves, width=4).grid(row=0, column=3)
        ttk.Label(eng, text="Without an engine it still solves forced mates (Puzzle Shogi).",
                  foreground="#888", font=("Segoe UI", 8)).grid(row=3, column=0, columnspan=3,
                                                                sticky="w", padx=8)

        cap = ttk.LabelFrame(parent, text="Capture from game")
        cap.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Button(cap, text="Capture board (3s delay)", command=self._capture_delayed
                   ).grid(row=0, column=0, **pad)
        self.cap_status = ttk.Label(cap, text="", foreground="#070")
        self.cap_status.grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(cap, text="Extra key").grid(row=1, column=0, sticky="e", **pad)
        self.capture_key = tk.StringVar(value="")     # optional; the paddle is the main path
        ttk.Entry(cap, textvariable=self.capture_key, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(cap, text="Judgment PAUSES when it loses focus, so clicking this window grabs "
                  "the paused screen. Main fix: with the Shogi tab selected, press your confirm "
                  "hotkey — the R4 back paddle / Insert (set on the Play tab) — while the GAME is "
                  "focused. Instant, no pause. The button instead waits 3s so you can click back "
                  "to the game. 'Extra key' is an optional separate key that captures from any "
                  "tab. Calibrate the board box first: calibrate mark --game shogi.",
                  foreground="#888", font=("Segoe UI", 8), wraplength=500
                  ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8)
        self._cap_pollers = set()
        self.capture_key.trace_add("write", lambda *_: self._install_capture_hotkey())
        self._install_capture_hotkey()

        bar = ttk.Frame(parent)
        bar.grid(row=4, column=0, sticky="w", **pad)
        ttk.Button(bar, text="Advise", command=self._advise).grid(row=0, column=0, **pad)
        self.status = ttk.Label(bar, text="", foreground="#070")
        self.status.grid(row=0, column=1, sticky="w", **pad)

        self.out = tk.Text(parent, height=16, width=46, wrap="none", bg="#0a0a0a",
                           fg="#d8d8d8", font=("Consolas", 10), state="disabled")
        self.out.grid(row=5, column=0, sticky="nsew", **pad)
        parent.rowconfigure(5, weight=1)

    # ----------------------------------------------------------------- logic ---
    def _browse_engine(self):
        import os
        from tkinter import filedialog
        p = filedialog.askopenfilename(
            title="USI engine", initialdir=str(self._root_dir),
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if p:
            try:
                p = os.path.relpath(p, self._root_dir)
            except ValueError:
                pass
            self.engine_path.set(p)
            self.use_engine.set(True)

    def _set_output(self, text):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)
        self.out.configure(state="disabled")

    def _ensure_engine(self):
        """Lazily start (and reuse) the USI engine; restart if the path changed.
        Runs on the worker thread — does no tk work."""
        path = self.engine_path.get().strip()
        if not path:
            return None
        if self._engine is not None and self._engine_started_for == path:
            return self._engine
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:                    # noqa: BLE001
                pass
            self._engine = None
        self._engine = UsiEngine(path, options=self._engine_options).start()
        self._engine_started_for = path
        return self._engine

    def _advise(self):
        state, err = build_state(self.sfen.get(), self.moves.get())
        if err:
            self.status.configure(text="invalid position", foreground="#a00")
            self._set_output(err)
            return
        self.status.configure(text="thinking...", foreground="#888")
        self._set_output(state.render() + "\n\n(thinking...)")
        self._gen += 1
        gen = self._gen
        use_engine = self.use_engine.get()
        try:
            movetime = int(self.movetime.get() or DEFAULT_MOVETIME)
            mate_moves = int(self.mate_moves.get() or DEFAULT_MATE_MOVES)
        except ValueError:
            self.status.configure(text="think/mate must be numbers", foreground="#a00")
            return

        def work():
            try:
                engine = self._ensure_engine() if use_engine else None
                out = best_move(state, engine=engine, mate_moves=mate_moves,
                                movetime_ms=movetime)
                text = state.render() + "\n\n" + format_advice(out)
                ok = True
            except Exception as e:               # noqa: BLE001 - report, don't crash the GUI
                text = state.render() + f"\n\nengine error: {e}"
                ok = False
            self.root.after(0, lambda: self._deliver(gen, text, ok))

        threading.Thread(target=work, daemon=True).start()

    def _deliver(self, gen, text, ok):
        if gen != self._gen:
            return                               # a newer Advise superseded this one
        self._set_output(text)
        self.status.configure(text="" if ok else "engine error",
                              foreground="#070" if ok else "#a00")

    def _install_capture_hotkey(self):
        """Poll a global key so Capture can fire while the *game* is focused (the
        only way to grab a live, un-paused frame). Windows-only; one poller per VK,
        reused if the key is re-entered."""
        import os
        if os.name != "nt":
            return
        from .live import _VK, _key_poller
        vk = _VK.get(self.capture_key.get().strip().lower())
        if vk is not None and vk not in self._cap_pollers:
            self._cap_pollers.add(vk)
            _key_poller(self.root, vk, self._do_capture)

    def _capture_delayed(self, secs=3):
        """Countdown then capture — gives you time to click back to the game so it
        un-pauses before the grab. (The hotkey is the cleaner path.)"""
        if secs <= 0:
            self._do_capture()
            return
        self.cap_status.configure(text=f"capturing in {secs}s — click the game window now",
                                  foreground="#888")
        self.root.after(1000, lambda: self._capture_delayed(secs - 1))

    def _do_capture(self):
        """Grab the game window and save the frame (+ 81 board cells if the board
        ROI is calibrated). Refuses a paused/dimmed grab. This is the bootstrap for
        piece recognition: capture a real board, then label the cells."""
        import time

        try:
            import cv2
            from .live import _screen_dimmed, grab_frame, load_config
            from ..capture.screen import ScreenGrabber
            from ..vision.shogi_board import occupancy_grid, save_cells
        except Exception as e:                       # noqa: BLE001
            self.cap_status.configure(text=f"capture deps missing: {e}", foreground="#a00")
            return
        cfg_path = self._root_dir / "config" / "regions.json"
        if not cfg_path.exists():
            self.cap_status.configure(text="no config/regions.json — calibrate first",
                                      foreground="#a00")
            return
        try:
            cfg = load_config(str(cfg_path))
            with ScreenGrabber(monitor=cfg.get("monitor", 1)) as g:
                frame = grab_frame(g, cfg)
        except Exception as e:                       # noqa: BLE001
            self.cap_status.configure(text=f"grab failed: {e}", foreground="#a00")
            return
        if frame is None or getattr(frame, "size", 0) == 0:
            win = cfg.get("window")
            self.cap_status.configure(
                text=(f"'{win}' window not found — open Judgment" if win else "no frame"),
                foreground="#a00")
            return
        if _screen_dimmed(frame):
            self.cap_status.configure(
                text="screen looks paused/dimmed — keep Judgment focused (use the hotkey)",
                foreground="#a00")
            return

        ts = time.strftime("%Y%m%d_%H%M%S")
        out = self._root_dir / "data" / "shogi"
        (out / "frames").mkdir(parents=True, exist_ok=True)
        fpath = out / "frames" / f"{ts}.png"
        cv2.imwrite(str(fpath), frame)
        board = (cfg.get("shogi") or {}).get("board")
        if not board or list(board) == [0, 0, 0, 0]:
            self.cap_status.configure(text=f"saved frame; calibrate the board box next",
                                      foreground="#070")
            self._set_output(f"Saved {frame.shape[1]}x{frame.shape[0]} frame:\n{fpath}\n\n"
                             f"Next: calibrate mark --game shogi --image \"{fpath}\"")
            return
        paths = save_cells(frame, board, str(out / "cells" / ts))
        occ = occupancy_grid(frame, board)
        n = sum(v for row in occ for v in row)
        self.cap_status.configure(text=f"saved frame + {len(paths)} cells ({n} occupied)",
                                  foreground="#070")
        grid_txt = "\n".join("".join("#" if v else "." for v in row) for row in occ)
        self._set_output(f"Saved frame + 81 cells -> data/shogi/cells/{ts}/\n\n"
                         f"occupancy (# = piece):\n{grid_txt}\n\n"
                         f"Next: label these cells into a piece template library to read SFEN.")

    def close(self):
        """Shut the engine down (called when the launcher quits)."""
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:                    # noqa: BLE001
                pass
            self._engine = None
