"""The launcher's Shogi Labels tab — manual verification + labelling of pieces.

Mirrors the poker Labels tab: a queue of cell crops the recognizer couldn't place
(banked to ``data/shogi/review/`` during play, e.g. promoted pieces) → preview a
crop → the **human** assigns the piece (owner + type + promoted) → it's saved as a
correctly-labelled template. Promoted-kanji disambiguation needs human eyes, so
labelling is authoritative here, not the pixel guess.

A small template manager lets you delete a mislabelled template, and "Capture
unread" pulls the current board's unreadable cells into the queue on demand.

Non-tk helpers (``piece_code``) are module-level for testing.
"""
from __future__ import annotations

import base64
import glob
import os

# (display name, SFEN letter), in the usual order.
PIECES = [("Pawn", "P"), ("Lance", "L"), ("Knight", "N"), ("Silver", "S"),
          ("Gold", "G"), ("Bishop", "B"), ("Rook", "R"), ("King", "K")]
_LETTER = dict(PIECES)


def piece_code(piece_name, yours, promoted):
    """(name, owner, promoted) -> SFEN code. Yours = uppercase (sente); promoted
    prefixes ``+`` (ignored for Gold/King, which can't promote)."""
    letter = _LETTER[piece_name]
    code = letter if yours else letter.lower()
    if promoted and letter not in ("G", "K"):
        code = "+" + code
    return code


class ShogiLabelsTab:
    def __init__(self, parent, tk, ttk, root, root_dir):
        self.tk, self.ttk, self.root = tk, ttk, root
        self._root_dir = root_dir
        self._review_dir = root_dir / "data" / "shogi" / "review"
        self._templates_dir = root_dir / "data" / "shogi" / "templates"
        self._paths = []                 # review crop paths, parallel to the listbox
        self._preview_img = None         # keep a ref so tk doesn't GC the PhotoImage
        self._rec = None
        self._build(parent)

    # ----------------------------------------------------------------- build ---
    def _build(self, parent):
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 6, "pady": 3}
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(1, weight=1)

        ttk.Label(parent, text="Crops the reader couldn't place (banked during play). Pick one, "
                  "check the picture, set the piece, and Save — that teaches the recognizer.",
                  foreground="#555", font=("Segoe UI", 9), wraplength=520
                  ).grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        # left: the queue of crops to label
        left = ttk.Frame(parent); left.grid(row=1, column=0, sticky="ns", **pad)
        self.listbox = tk.Listbox(left, width=26, height=16, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())
        btns = ttk.Frame(left); btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Refresh", command=self._reload).grid(row=0, column=0)
        ttk.Button(btns, text="Capture unread", command=self._capture_unread).grid(row=0, column=1, padx=4)
        self.count = ttk.Label(left, text="", foreground="#070"); self.count.pack(anchor="w")

        # right: preview + the labelling controls
        right = ttk.Frame(parent); right.grid(row=1, column=1, sticky="nw", **pad)
        self.preview = ttk.Label(right, text="(select a crop)", anchor="center",
                                 width=18, background="#0a0a0a", foreground="#888")
        self.preview.grid(row=0, column=0, columnspan=4, pady=4)
        self.guess = ttk.Label(right, text="", foreground="#888", font=("Segoe UI", 8))
        self.guess.grid(row=1, column=0, columnspan=4, sticky="w")

        ttk.Label(right, text="Owner:").grid(row=2, column=0, sticky="e", **pad)
        self.owner = tk.StringVar(value="opp")
        ttk.Radiobutton(right, text="Mine", value="you", variable=self.owner).grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(right, text="Opponent", value="opp", variable=self.owner).grid(row=2, column=2, sticky="w")

        ttk.Label(right, text="Piece:").grid(row=3, column=0, sticky="e", **pad)
        self.piece = tk.StringVar(value="Pawn")
        ttk.Combobox(right, textvariable=self.piece, values=[n for n, _ in PIECES],
                     width=10, state="readonly").grid(row=3, column=1, columnspan=2, sticky="w")
        self.promoted = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Promoted (+)", variable=self.promoted).grid(row=4, column=1, sticky="w")

        ttk.Button(right, text="Save as template", command=self._save
                   ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        ttk.Button(right, text="Delete crop", command=self._delete_crop
                   ).grid(row=5, column=2, sticky="w", **pad)
        self.status = ttk.Label(right, text="", foreground="#070"); self.status.grid(
            row=6, column=0, columnspan=4, sticky="w", **pad)

        # template manager: see what's labelled, delete a mistake
        tm = ttk.LabelFrame(parent, text="Templates (delete a mislabel)")
        tm.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        self.templates = tk.StringVar()
        self.tpl_box = ttk.Combobox(tm, textvariable=self.templates, width=14, state="readonly")
        self.tpl_box.grid(row=0, column=0, **pad)
        ttk.Button(tm, text="Delete template", command=self._delete_template).grid(row=0, column=1, **pad)
        self.tpl_status = ttk.Label(tm, text="", foreground="#070"); self.tpl_status.grid(row=0, column=2, **pad)

        self._reload()

    # ----------------------------------------------------------------- logic ---
    def _reload(self):
        self.listbox.delete(0, "end")
        self._paths = sorted(glob.glob(str(self._review_dir / "*.png")))
        for p in self._paths:
            self.listbox.insert("end", os.path.basename(p))
        self.count.configure(text=f"{len(self._paths)} crop(s) to label")
        self._reload_templates()
        self._rec = None                 # force recognizer reload (templates may have changed)

    def _reload_templates(self):
        import json
        man = self._templates_dir / "manifest.json"
        codes = []
        if man.exists():
            codes = sorted(set(json.load(open(man, encoding="utf-8")).values()))
        self.tpl_box.configure(values=codes)

    def _recognizer(self):
        if self._rec is None:
            try:
                from ..vision.shogi_pieces import PieceRecognizer
                self._rec = PieceRecognizer(str(self._templates_dir))
            except Exception:            # noqa: BLE001 - no library yet
                self._rec = None
        return self._rec

    def _selected_path(self):
        sel = self.listbox.curselection()
        return self._paths[sel[0]] if sel else None

    def _photo(self, img, size=140):
        import cv2
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_NEAREST)
        ok, buf = cv2.imencode(".png", img)
        return self.tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode()) if ok else None

    def _on_select(self):
        import cv2
        p = self._selected_path()
        if not p:
            return
        img = cv2.imread(p)
        if img is None:
            return
        self._preview_img = self._photo(img)
        if self._preview_img is not None:
            self.preview.configure(image=self._preview_img, text="")
        rec = self._recognizer()
        if rec is not None:
            code, score = rec.classify_conf(img)
            self.guess.configure(text=f"recognizer guess: {code or 'empty'} ({score:.2f}) — verify and fix")

    def _save(self):
        import cv2
        p = self._selected_path()
        if not p:
            self.status.configure(text="select a crop first", foreground="#a00"); return
        code = piece_code(self.piece.get(), self.owner.get() == "you", self.promoted.get())
        try:
            from ..vision.shogi_pieces import save_template_from_crop
            save_template_from_crop(cv2.imread(p), code, str(self._templates_dir))
            os.remove(p)                 # labelled -> leave the queue
        except Exception as e:           # noqa: BLE001
            self.status.configure(text=f"save failed: {e}", foreground="#a00"); return
        self._reload()
        self.status.configure(text=f"saved template '{code}' — reset the board on the Shogi tab to use it",
                              foreground="#070")

    def _delete_crop(self):
        p = self._selected_path()
        if not p:
            return
        try:
            os.remove(p)
        except OSError:
            pass
        self._reload()
        self.status.configure(text="crop deleted", foreground="#070")

    def _delete_template(self):
        code = self.templates.get().strip()
        if not code:
            return
        from ..vision.shogi_pieces import remove_template
        ok = remove_template(code, str(self._templates_dir))
        self._reload_templates()
        self.tpl_status.configure(text=(f"removed '{code}'" if ok else "not found"),
                                  foreground="#070" if ok else "#a00")

    def _capture_unread(self):
        """Grab the game (3s delay so you can refocus it) and add the board's
        unreadable cells to the queue."""
        self.status.configure(text="capturing in 3s — click the game window", foreground="#888")
        self.root.after(3000, self._do_capture_unread)

    def _do_capture_unread(self):
        import time
        try:
            import cv2
            from .live import _screen_dimmed, grab_frame, load_config
            from ..capture.screen import ScreenGrabber
            from ..vision.shogi_board import ShogiBoardReader, save_review_cells
            from ..vision.shogi_pieces import PieceRecognizer
        except Exception as e:           # noqa: BLE001
            self.status.configure(text=f"deps missing: {e}", foreground="#a00"); return
        cfg_path = self._root_dir / "config" / "regions.json"
        if not cfg_path.exists():
            self.status.configure(text="no config/regions.json", foreground="#a00"); return
        cfg = load_config(str(cfg_path))
        board = (cfg.get("shogi") or {}).get("board")
        if not board or list(board) == [0, 0, 0, 0]:
            self.status.configure(text="board not calibrated", foreground="#a00"); return
        try:
            with ScreenGrabber(monitor=cfg.get("monitor", 1)) as g:
                frame = grab_frame(g, cfg)
        except Exception as e:           # noqa: BLE001
            self.status.configure(text=f"grab failed: {e}", foreground="#a00"); return
        if frame is None or getattr(frame, "size", 0) == 0 or _screen_dimmed(frame):
            self.status.configure(text="no live frame (keep the game focused)", foreground="#a00"); return
        try:
            reader = ShogiBoardReader(board, recognizer=PieceRecognizer(str(self._templates_dir)))
            cells = reader.uncertain_cells(frame)
        except Exception as e:           # noqa: BLE001
            self.status.configure(text=f"need a template library first: {e}", foreground="#a00"); return
        tag = "cap_" + time.strftime("%Y%m%d_%H%M%S")
        save_review_cells(frame, board, cells, str(self._review_dir), tag)
        self._reload()
        self.status.configure(text=f"added {len(cells)} unread cell(s) to label", foreground="#070")
