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
import queue
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


# --- human-readable rendering -------------------------------------------------
# Piece names by python-shogi piece_type.
PIECE_NAMES = {
    1: "Pawn", 2: "Lance", 3: "Knight", 4: "Silver", 5: "Gold",
    6: "Bishop", 7: "Rook", 8: "King",
    9: "+Pawn (Tokin)", 10: "+Lance", 11: "+Knight", 12: "+Silver",
    13: "Horse (+Bishop)", 14: "Dragon (+Rook)",
}
_RANKS = "abcdefghi"


def _sq_rc(sq):
    """USI square '3i' -> (row, col) in the on-screen grid (row 0 = top, col 0 =
    leftmost = file 9)."""
    return _RANKS.index(sq[1]), 9 - int(sq[0])


def _board_grid(sfen):
    """SFEN board field -> 9×9 of piece codes ('' empty, '+R' promoted)."""
    grid = []
    for rank in sfen.split()[0].split("/"):
        row, i = [], 0
        while i < len(rank):
            ch = rank[i]
            if ch.isdigit():
                row += [""] * int(ch); i += 1
            elif ch == "+":
                row.append("+" + rank[i + 1]); i += 2
            else:
                row.append(ch); i += 1
        grid.append(row)
    return grid


def describe_move(sfen, usi):
    """USI move -> plain English: 'Silver  3i → 4h', 'drop Gold → 5b'."""
    import shogi
    mv = shogi.Move.from_usi(usi)
    if mv.drop_piece_type:
        return f"drop {PIECE_NAMES.get(mv.drop_piece_type, 'piece')} → {usi.split('*')[1]}"
    pc = shogi.Board(sfen).piece_at(mv.from_square)
    name = PIECE_NAMES.get(pc.piece_type, "piece") if pc else "piece"
    out = f"{name}  {usi[:2]} → {usi[2:4]}"
    return out + "  (promote)" if mv.promotion else out


def render_board(sfen, usi=None):
    """ASCII board with file/rank labels; marks the move's From/To squares."""
    grid = _board_grid(sfen)
    frm = to = None
    if usi:
        if "*" in usi:
            to = _sq_rc(usi.split("*")[1])
        else:
            frm, to = _sq_rc(usi[:2]), _sq_rc(usi[2:4])
    lines = ["    9 8 7 6 5 4 3 2 1"]
    for r in range(9):
        cells = []
        for c in range(9):
            if (r, c) == frm:
                cells.append("F")
            elif (r, c) == to:
                cells.append("T")
            else:
                v = grid[r][c]
                cells.append(v[-1] if v else ".")   # promoted shown as its base letter
        lines.append(f" {_RANKS[r]}  " + " ".join(cells))
    return "\n".join(lines)


def format_result(sfen, out):
    """Full readable advice for the tab: labeled board + named move + legend."""
    mv = out.get("move")
    if not mv:
        return render_board(sfen) + "\n\n" + out.get("note", "no advice available")
    head = f"BEST MOVE:  {describe_move(sfen, mv)}"
    if out.get("source") == "mate":
        head += f"     (forced mate in {out['mate_in']})\nline:  " + " ".join(out["pv"])
    else:
        head += "     (engine)"
    legend = ("\n  F = from, T = to.   CAPITALS = your pieces (bottom), "
              "lowercase = opponent (top)."
              "\n  files count right→left (1 = rightmost); ranks a (top)→i (bottom).")
    return f"{render_board(sfen, mv)}\n\n{head}{legend}"


def format_overlay_line(sfen, out):
    """Compact advice for the floating overlay."""
    mv = out.get("move")
    if not mv:
        return out.get("note", "no advice")
    if out.get("source") == "mate":
        return f"MATE in {out['mate_in']}:  {describe_move(sfen, mv)}"
    return f"BEST:  {describe_move(sfen, mv)}"


class ShogiTab:
    def __init__(self, parent, tk, ttk, root, root_dir):
        self.tk, self.ttk, self.root = tk, ttk, root
        self._root_dir = root_dir
        self._engine = None
        self._engine_started_for = None          # path the live engine was started with
        self._gen = 0                            # ignore results from superseded clicks
        self._board = None                       # StableBoardReader (lazy; needs templates)
        self._result_q = queue.Queue()           # worker -> main-thread results (tk isn't thread-safe)
        self._overlay = None                     # floating SuggestionOverlay when Live read is on
        self._live = False                       # continuous-read loop running?
        self._grab = None                        # ScreenGrabber held for the loop
        self._cfg_live = None                    # regions.json cached for the loop
        self._last_live_sfen = None              # re-advise only when the board changes
        cfg_path, cfg_opts, cfg_movetime = load_engine_config(root_dir)
        self._engine_options = cfg_opts
        self._build(parent, cfg_path, cfg_movetime)
        self.root.after(120, self._poll_results)

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
        ttk.Button(cap, text="New game (reset)", command=self._reset_board
                   ).grid(row=0, column=2, **pad)
        self.live_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cap, text="Live read + overlay", variable=self.live_var,
                        command=self._toggle_live).grid(row=0, column=3, **pad)
        self.train_var = tk.BooleanVar(value=True)   # bank live frames/cells for training
        ttk.Checkbutton(cap, text="Save training data", variable=self.train_var
                        ).grid(row=0, column=4, **pad)
        self.cap_status = ttk.Label(cap, text="", foreground="#070")
        self.cap_status.grid(row=0, column=5, sticky="w", **pad)
        ttk.Label(cap, text="Extra key").grid(row=1, column=0, sticky="e", **pad)
        self.capture_key = tk.StringVar(value="")     # optional; the paddle is the main path
        ttk.Entry(cap, textvariable=self.capture_key, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(cap, text="Judgment PAUSES when it loses focus, so clicking this window grabs "
                  "the paused screen. Main fix: with the Shogi tab selected, press your confirm "
                  "hotkey — the R4 back paddle / Insert (set on the Play tab) — while the GAME is "
                  "focused. Instant, no pause. The button instead waits 3s so you can click back "
                  "to the game. 'Extra key' is an optional separate key that captures from any "
                  "tab. 'Live read + overlay' floats advice over the game, re-reading every "
                  "~1.2s; 'Save training data' banks each distinct live position (+ unread cells "
                  "= promoted pieces to label) to data/shogi/. Calibrate the board first: "
                  "calibrate mark --game shogi.",
                  foreground="#888", font=("Segoe UI", 8), wraplength=500
                  ).grid(row=2, column=0, columnspan=6, sticky="w", padx=8)
        self._cap_pollers = set()
        self._train_n = 0                        # counter for unique training filenames
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

    def _ensure_engine(self, path):
        """Lazily start (and reuse) the USI engine; restart if the path changed.
        Runs on the worker thread, so ``path`` is passed in (read on the main
        thread) — never touch a tk variable here."""
        path = (path or "").strip()
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
        engine_path = self.engine_path.get()     # read tk vars on the main thread only
        try:
            movetime = int(self.movetime.get() or DEFAULT_MOVETIME)
            mate_moves = int(self.mate_moves.get() or DEFAULT_MATE_MOVES)
        except ValueError:
            self.status.configure(text="think/mate must be numbers", foreground="#a00")
            return

        sfen = state.sfen

        def work():
            try:
                engine = self._ensure_engine(engine_path) if use_engine else None
                out = best_move(state, engine=engine, mate_moves=mate_moves,
                                movetime_ms=movetime)
                full = format_result(sfen, out)
                compact = format_overlay_line(sfen, out)
                ok = True
            except Exception as e:               # noqa: BLE001 - report, don't crash the GUI
                full = render_board(sfen) + f"\n\nengine error: {e}"
                compact = f"engine error: {e}"
                ok = False
            self._result_q.put((gen, full, compact, ok))  # hand back to main thread; no tk here

        threading.Thread(target=work, daemon=True).start()

    def _poll_results(self):
        """Drain worker results on the *main* thread (tk is not thread-safe, so the
        worker can't update widgets itself). Rescheduled for the tab's lifetime."""
        try:
            while True:
                gen, full, compact, ok = self._result_q.get_nowait()
                if gen == self._gen:             # ignore superseded Advise calls
                    self._set_output(full)
                    self.status.configure(text="" if ok else "engine error",
                                          foreground="#070" if ok else "#a00")
                    if self._overlay is not None:
                        try:
                            self._overlay.update_text(compact)
                        except Exception:        # noqa: BLE001
                            pass
        except queue.Empty:
            pass
        try:
            self.root.after(120, self._poll_results)
        except Exception:                        # noqa: BLE001 - window gone -> stop
            pass

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
        save_cells(frame, board, str(out / "cells" / ts))   # keep crops (extend templates later)

        reader = self._ensure_board_reader(board)
        if reader is None:                          # no template library yet -> occupancy only
            occ = occupancy_grid(frame, board)
            n = sum(v for row in occ for v in row)
            grid_txt = "\n".join("".join("#" if v else "." for v in row) for row in occ)
            self.cap_status.configure(text=f"saved frame + 81 cells ({n} occupied)",
                                      foreground="#070")
            self._set_output(f"Saved frame + 81 cells -> data/shogi/cells/{ts}/\n\n"
                             f"occupancy (# = piece):\n{grid_txt}\n\n"
                             f"No template library yet — build it from an opening capture to "
                             f"read pieces into an SFEN.")
            return

        # Fold this frame into the persistent board: hand-obscured cells keep their
        # prior value, so successive captures (as the hand moves) fill the board in.
        reader.update(frame)
        obscured = reader.obscured(frame)
        sfen = self._sfen_with_hands(frame, cfg)
        self.sfen.set(sfen)
        self.moves.set("")
        note = f" ({obscured} cell(s) obscured — kept prior; capture again)" if obscured else ""
        self.cap_status.configure(text=f"read board{note}", foreground="#070")
        self._advise()                              # show the best move for the read position

    def _sfen_with_hands(self, frame, cfg):
        """Board grid (persistent) + captured pieces read from the two pools ->
        full SFEN. Falls back to empty hands if the pools aren't calibrated."""
        from ..vision.shogi_board import grid_to_sfen
        hands = None
        sh = cfg.get("shogi") or {}
        you, opp = sh.get("hand_you"), sh.get("hand_opp")
        if you and opp:
            try:
                from ..vision.shogi_hand import read_hands
                hands = read_hands(frame, you, opp,
                                   str(self._root_dir / "data" / "shogi" / "templates"))
            except Exception:                        # noqa: BLE001 - hands optional
                hands = None
        return grid_to_sfen(self._board.grid, "b", hands)

    def _ensure_board_reader(self, board_roi):
        """A persistent StableBoardReader if a template library exists, else None.
        Built once and reused so captures accumulate into one board."""
        if self._board is not None:
            return self._board
        tdir = self._root_dir / "data" / "shogi" / "templates"
        if not (tdir / "manifest.json").exists():
            return None
        try:
            from ..vision.shogi_board import ShogiBoardReader, StableBoardReader
            from ..vision.shogi_pieces import PieceRecognizer
            rec = PieceRecognizer(str(tdir))
            self._board = StableBoardReader(ShogiBoardReader(board_roi, recognizer=rec))
        except Exception as e:                       # noqa: BLE001
            self.cap_status.configure(text=f"recognizer unavailable: {e}", foreground="#a00")
            return None
        return self._board

    def _reset_board(self):
        """Clear the persistent board AND drop the cached recognizer so any newly
        added templates (e.g. a freshly labeled promoted piece) are reloaded on the
        next capture — no launcher restart needed."""
        self._board = None
        self._last_live_sfen = None
        self.cap_status.configure(text="board reset (templates reloaded) — capture to read",
                                  foreground="#070")

    # ------------------------------------------------------- live read loop ---
    LIVE_INTERVAL_MS = 1200

    def _toggle_live(self):
        if self.live_var.get():
            self._start_live()
        else:
            self._stop_live()

    def _start_live(self):
        """Begin the continuous read loop + floating overlay. Needs a calibrated
        board ROI and a template library; otherwise refuses and unticks."""
        from .live import load_config
        from ..capture.screen import ScreenGrabber
        from .overlay import SuggestionOverlay
        cfg_path = self._root_dir / "config" / "regions.json"
        if not cfg_path.exists():
            self._live_fail("no config/regions.json — calibrate first")
            return
        cfg = load_config(str(cfg_path))
        board = (cfg.get("shogi") or {}).get("board")
        if not board or list(board) == [0, 0, 0, 0]:
            self._live_fail("board not calibrated — run calibrate mark --game shogi")
            return
        if self._ensure_board_reader(board) is None:
            self._live_fail("no template library — capture an opening board first")
            return
        try:
            self._grab = ScreenGrabber(monitor=cfg.get("monitor", 1)); self._grab.__enter__()
        except Exception as e:                       # noqa: BLE001
            self._live_fail(f"capture init failed: {e}")
            return
        self._cfg_live = cfg
        self._last_live_sfen = None
        self._overlay = SuggestionOverlay(master=self.root, input_enabled=False, x=40, y=40)
        self._overlay.update_text("shogi: waiting for the board…")
        self._live = True
        self.cap_status.configure(text="live read ON — overlay floating over the game",
                                  foreground="#070")
        self.root.after(self.LIVE_INTERVAL_MS, self._live_tick)

    def _live_fail(self, msg):
        self.live_var.set(False)
        self.cap_status.configure(text=msg, foreground="#a00")

    def _live_tick(self):
        if not self._live:
            return
        from .live import _screen_dimmed, grab_frame
        from ..capture.window import is_foreground
        try:
            win = self._cfg_live.get("window")
            frame = grab_frame(self._grab, self._cfg_live)
            if frame is None or getattr(frame, "size", 0) == 0:
                self._overlay.update_text("shogi: game window not found")
            elif (win and not is_foreground(win)) or _screen_dimmed(frame):
                pass                                 # not focused / paused -> keep last advice
            else:
                self._board.update(frame)
                sfen = self._sfen_with_hands(frame, self._cfg_live)
                if sfen != self._last_live_sfen:     # board changed -> recompute
                    self._last_live_sfen = sfen
                    self.sfen.set(sfen)
                    self.moves.set("")
                    self._advise()                   # threaded; result updates tab + overlay
                    if self.train_var.get():
                        self._save_training(frame)   # bank this distinct position
        except Exception as e:                       # noqa: BLE001 - keep the loop alive
            try:
                self._overlay.update_text(f"shogi: read hiccup ({e})")
            except Exception:                        # noqa: BLE001
                pass
        finally:
            if self._live:
                self.root.after(self.LIVE_INTERVAL_MS, self._live_tick)

    def _save_training(self, frame):
        """Bank a distinct live position for training: the full frame, plus crops
        of the cells the recognizer couldn't read (likely promoted pieces to add to
        the library). Banked only when a *few* cells are unread — a large unread
        cluster is usually the hand sweeping across, which is noise."""
        import time
        import cv2
        from ..vision.shogi_board import save_review_cells
        try:
            self._train_n += 1
            tag = time.strftime("%Y%m%d_%H%M%S") + f"_{self._train_n:03d}"
            out = self._root_dir / "data" / "shogi"
            (out / "frames").mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out / "frames" / f"live_{tag}.png"), frame)
            board = (self._cfg_live.get("shogi") or {}).get("board")
            unread = set(self._board.reader.uncertain_cells(frame))
            # The hand cursor covers a CONTIGUOUS blob; a promoted piece is an
            # ISOLATED unread cell. Bank only cells with no unread neighbour (8-conn)
            # so review/ collects real unknowns, not fingers.
            isolated = [(r, c) for (r, c) in unread
                        if not any((r + dr, c + dc) in unread
                                   for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0))]
            if board and isolated:
                save_review_cells(frame, board, isolated, str(out / "review"), f"live_{tag}")
        except Exception:                            # noqa: BLE001 - never break the loop
            pass

    def _stop_live(self):
        self._live = False
        if self._grab is not None:
            try:
                self._grab.__exit__(None, None, None)
            except Exception:                        # noqa: BLE001
                pass
            self._grab = None
        if self._overlay is not None:
            try:
                self._overlay.close()
            except Exception:                        # noqa: BLE001
                pass
            self._overlay = None
        self.cap_status.configure(text="live read off", foreground="#070")

    def close(self):
        """Stop the live loop + overlay and shut the engine down (launcher quit)."""
        self._stop_live()
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:                    # noqa: BLE001
                pass
            self._engine = None
