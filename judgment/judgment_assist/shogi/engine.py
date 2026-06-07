"""USI engine driver + the shogi advisor facade.

A full-match advisor needs positional judgement, which means a real engine. The
USI (Universal Shogi Interface) protocol is the standard; :class:`UsiEngine`
drives any USI binary over stdin/stdout. The binary itself is **optional and
deferred** (see ``SHOGI.md``) — until one is configured, the advisor still gives
exact advice whenever a forced mate exists, via the pure-Python solver.

``best_move`` is the single entry point: it tries a forced mate first (cheap and
exact), then asks the engine if one is wired up.
"""
from __future__ import annotations

import os
import subprocess
import threading

from .board import ShogiState
from .mate import find_mate, mate_in


class UsiEngine:
    """Minimal USI engine driver. ``path`` is the engine executable.

    Usage::

        eng = UsiEngine(r"C:\\engines\\YaneuraOu.exe")
        eng.start()
        move = eng.best_move(state.sfen, movetime_ms=1000)
        eng.close()
    """

    def __init__(self, path, options: dict | None = None):
        # ``path`` may be the executable, or a full command list (exe + args).
        cmd = list(path) if isinstance(path, (list, tuple)) else [path]
        # Resolve the executable to an absolute path: a bare relative path breaks
        # under Popen when the child's working directory differs from ours.
        exe = os.path.expanduser(cmd[0])
        if os.path.sep in exe or (os.altsep and os.altsep in exe):
            exe = os.path.abspath(exe)
        cmd[0] = exe
        self.cmd = cmd
        self.options = options or {}
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def start(self) -> "UsiEngine":
        self._proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._send("usi")
        self._wait_for("usiok")
        for name, value in self.options.items():
            self._send(f"setoption name {name} value {value}")
        self._send("isready")
        self._wait_for("readyok")
        return self

    def best_move(self, sfen: str, movetime_ms: int = 1000) -> str | None:
        """Ask the engine for the best move in ``sfen``. Returns USI or None
        (``resign``/``win`` map to None)."""
        if self._proc is None:
            raise RuntimeError("engine not started; call start() first")
        with self._lock:
            self._send("usinewgame")
            self._send(f"position sfen {sfen}")
            self._send(f"go movetime {movetime_ms}")
            line = self._wait_for("bestmove")
        token = line.split()[1] if line and len(line.split()) > 1 else None
        return None if token in (None, "resign", "win") else token

    def close(self):
        if self._proc is not None:
            try:
                self._send("quit")
            except Exception:  # noqa: BLE001 - we're tearing down anyway
                pass
            self._proc.terminate()
            self._proc = None

    # ---- protocol plumbing ---------------------------------------------------
    def _send(self, cmd: str):
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()

    def _wait_for(self, prefix: str) -> str:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if line.startswith(prefix):
                return line
        raise RuntimeError(f"engine closed before '{prefix}'")


def best_move(state: ShogiState, engine: UsiEngine | None = None,
              mate_moves: int = 7, movetime_ms: int = 1000) -> dict:
    """Recommend a move for the side to move.

    Strategy: look for a forced mate within ``mate_moves`` first (exact, no
    binary). If none and an ``engine`` is supplied, ask it. Otherwise report that
    positional advice needs an engine.

    Returns ``{move, source, ...}`` where ``source`` is ``"mate"``, ``"engine"``,
    or ``"none"``.
    """
    # Iterative deepening: find the *shortest* forced mate. A fixed depth would
    # report a non-minimal line (a wasted tempo that still mates) on very winning
    # positions, and miss reporting a mate-in-1 as such.
    #
    # ``require_check=True`` (tsume-style) is essential here, not just a nicety:
    # forced mates in real positions are virtually always continuous checks, and
    # restricting to checking moves prunes the search from ~30^n to a handful —
    # without it, a deep search on a non-mating position (e.g. the opening) blows
    # up. The configured engine still finds any non-check tactical mate.
    for depth in range(1, mate_moves + 1):
        pv = find_mate(state.raw, depth, require_check=True)
        if pv:
            return {"move": pv[0], "pv": pv, "mate_in": mate_in(pv), "source": "mate"}
    if engine is not None:
        mv = engine.best_move(state.sfen, movetime_ms)
        return {"move": mv, "source": "engine"}
    return {
        "move": None,
        "source": "none",
        "note": "no forced mate; configure a USI engine for positional advice",
    }
