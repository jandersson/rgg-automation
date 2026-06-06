"""The launcher's Labels tab, extracted from ``LauncherApp`` into its own class.

Reviews and edits the whole training library (``data/poker_cards``): list every
crop the reader learns from, preview it, fix its rank/suit, mark it reviewed,
skip or delete it, and create new crops by capturing from the game or importing
saved frames. Edits hit ``labels.json`` at once and (if a poker session is
running) resync the writer / refit the detector.

It's decoupled from the launcher via three callables passed in:
``get_session()`` (the running poker session dict, or None — for live-bank append
and writer/reader resync), ``get_config_path()`` (the resolved regions.json path),
and the ``root_dir`` (the ``judgment/`` root). The launcher drives it through the
public methods ``append_live_banks``, ``confirm_and_next`` and ``on_session_start``.
"""
from __future__ import annotations

import os
import subprocess


class LabelsTab:
    _SLOT_HUMAN = {"H0": "Hole 1", "H1": "Hole 2", "B0": "Board 1", "B1": "Board 2",
                   "B2": "Board 3", "B3": "Board 4", "B4": "Board 5"}
    _SUIT_SYM = {"clubs": "♣", "diamonds": "♦", "hearts": "♥", "spades": "♠"}
    _SUIT_LETTER = {"clubs": "c", "diamonds": "d", "hearts": "h", "spades": "s"}
    _RANKS = list("23456789TJQKA")
    _SUITS = ["c", "d", "h", "s"]

    def __init__(self, parent, tk, ttk, root, root_dir, get_session, get_config_path):
        self.tk, self.ttk, self.root = tk, ttk, root
        self._root_dir = root_dir
        self._session = get_session
        self._config_path = get_config_path
        self._build(parent)

    # ----------------------------------------------------------------- build ---
    def _build(self, parent):
        tk, ttk = self.tk, self.ttk
        from ..vision.poker_cards import LabelLibrary
        self._lib = LabelLibrary(str(self._root_dir / "data" / "poker_cards"))
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
        ttk.Label(top, text="Every crop the reader learns from. ✓ = reviewed (a label "
                  "you verified, or confirmed in play). Click one to preview, then "
                  "fix / mark reviewed / skip / delete.",
                  foreground="#555", font=("Segoe UI", 9), wraplength=470
                  ).grid(row=0, column=0, columnspan=5, sticky="w")
        ttk.Button(top, text="Refresh", command=self._reload_labels_list
                   ).grid(row=1, column=0, pady=4, sticky="w")
        ttk.Button(top, text="Open data folder", command=self._open_cards_dir
                   ).grid(row=1, column=1, padx=6)
        self._hide_reviewed = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Hide reviewed", variable=self._hide_reviewed,
                        command=self._reload_labels_list).grid(row=1, column=2, padx=4)
        self._labels_count = ttk.Label(top, text="", foreground="#070")
        self._labels_count.grid(row=1, column=3, padx=8, sticky="w")
        row2 = ttk.Frame(top)
        row2.grid(row=2, column=0, columnspan=5, sticky="w", pady=(2, 0))
        ttk.Label(row2, text="Sort:").grid(row=0, column=0)
        self._sort_var = tk.StringVar(value="Newest")
        ttk.Combobox(row2, values=["Newest", "By label", "By slot", "Hard cases first"],
                     textvariable=self._sort_var, width=15, state="readonly"
                     ).grid(row=0, column=1, padx=4)
        self._sort_var.trace_add("write", lambda *_: self._reload_labels_list())
        ttk.Button(row2, text="Next unreviewed →", command=self._select_next_unreviewed
                   ).grid(row=0, column=2, padx=10)
        ttk.Label(row2, text="(Enter / Space / your R4 button = mark reviewed + next)",
                  foreground="#888", font=("Segoe UI", 8)).grid(row=0, column=3)

        cols = ("when", "source", "slot", "label", "ok")
        self.labels_tree = ttk.Treeview(parent, columns=cols, show="headings", height=11)
        for c, w, head in (("when", 78, "When"), ("source", 74, "Source"),
                           ("slot", 74, "Slot"), ("label", 84, "Label"), ("ok", 34, "✓")):
            self.labels_tree.heading(c, text=head)
            self.labels_tree.column(c, width=w, anchor="center")
        self.labels_tree.grid(row=1, column=0, sticky="nsew", padx=(8, 0))
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.labels_tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.labels_tree.configure(yscrollcommand=sb.set)
        self.labels_tree.bind("<<TreeviewSelect>>", lambda e: self._show_label_crop())
        for seq in ("<Return>", "<space>"):           # keyboard sweep keys
            self.labels_tree.bind(seq, lambda e: (self.confirm_and_next(), "break")[1])

        mid = ttk.Frame(parent)
        mid.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        self._labels_preview = ttk.Label(mid, text="(select a crop to preview)",
                                          foreground="#888", compound="top")
        self._labels_preview.grid(row=0, column=0, rowspan=4, padx=(8, 14))
        ttk.Label(mid, text="Edit selected crop:", font=("Segoe UI", 9, "bold")
                  ).grid(row=0, column=1, columnspan=4, sticky="w")
        self._edit_rank = tk.StringVar()
        self._edit_suit = tk.StringVar()
        ttk.Label(mid, text="rank").grid(row=1, column=1, sticky="e")
        ttk.Combobox(mid, values=self._RANKS, textvariable=self._edit_rank, width=4,
                     state="readonly").grid(row=1, column=2, padx=2)
        ttk.Label(mid, text="suit").grid(row=1, column=3, sticky="e")
        ttk.Combobox(mid, values=self._SUITS, textvariable=self._edit_suit, width=4,
                     state="readonly").grid(row=1, column=4, padx=2)
        ttk.Button(mid, text="Save label", command=self._save_label
                   ).grid(row=2, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Button(mid, text="Mark reviewed ✓", command=self._mark_reviewed
                   ).grid(row=2, column=3, columnspan=2, sticky="ew")
        ttk.Button(mid, text="Skip (exclude)", command=self._skip_label
                   ).grid(row=3, column=1, columnspan=2, sticky="ew")
        ttk.Button(mid, text="Delete", command=self._delete_label
                   ).grid(row=3, column=3, columnspan=2, sticky="ew")
        self._refit_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mid, text="Refit detector after edits (live session)",
                        variable=self._refit_var).grid(row=4, column=1, columnspan=4, sticky="w")
        create = ttk.Frame(mid)
        create.grid(row=5, column=1, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(create, text="Add crops:", font=("Segoe UI", 9)).grid(row=0, column=0)
        ttk.Button(create, text="Capture from game", command=self._capture_from_game
                   ).grid(row=0, column=1, padx=4)
        ttk.Button(create, text="Import screenshots…", command=self._import_screenshots
                   ).grid(row=0, column=2)
        self._labels_msg = ttk.Label(parent, text="", foreground="#070")
        self._labels_msg.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        self._labels_img = None          # hold the PhotoImage ref against GC
        self._labels_path = {}           # tree iid (= crop path) -> crop path
        self._labels_key = {}            # tree iid -> labels.json key (frame#slot)
        self._labels_total = self._labels_needs = self._labels_reviewed = 0
        self._live_seen = 0
        self._cap_pid, self._cap_seq = os.getpid(), 0    # ids for captured crops
        self._suggest_reader, self._suggest_dirty = None, True   # lazy guess reader
        self._suspect_list, self._suspects = None, {}    # kNN label-consistency flags
        self._reload_labels_list()

    # ------------------------------------------------------- public (launcher) -
    def on_session_start(self):
        """A new poker session began — read its bank log from the top."""
        self._live_seen = 0

    def append_live_banks(self):
        """Per-tick: add the running advisor's freshly-banked crops at the top. These
        are labeled but NOT reviewed — confirming in play isn't a deliberate label
        check — so they stay visible (the worklist for the second pass) and the
        'Hide reviewed' filter never hides them."""
        s = self._session()
        if not s:
            return
        banked = s["advisor"].banked
        changed = False
        while self._live_seen < len(banked):
            b = banked[self._live_seen]
            self._live_seen += 1
            path = b.get("path")
            if not path or self.labels_tree.exists(path):
                continue
            self._labels_total += 1
            changed = True
            slot = b["slot"]
            vals = (b["time"], "Session", self._SLOT_HUMAN.get(slot, slot), b["card"], "")
            self.labels_tree.insert("", 0, iid=path, values=vals)
            self._labels_path[path] = path
            self._labels_key[path] = self._key_from(path, slot)
        if changed:
            self._update_labels_count()

    def confirm_and_next(self):
        """Enter / R4: confirm a labeled crop as reviewed (it's correct), then jump to
        the next unreviewed one — the fast path for sweeping the backlog."""
        iid, key = self._selected_key()
        if not key:
            return
        if "rank" in self._lib.labels.get(key, {}):
            self._suspect_list = None
            self._lib.reload()
            self._lib.set_reviewed(key)
            self._sync_writer()
            self._reload_labels_list()
        self._select_next_unreviewed()

    # ---------------------------------------------------------------- helpers --
    @staticmethod
    def _source_of(frame):
        if frame.startswith("frame"):
            return "Seed"
        if frame.startswith("live"):
            return "Session"
        if frame.startswith("cap"):
            return "Capture"
        if frame.startswith("obsc"):
            return "Obscured"
        return "Import"

    def _label_text(self, e):
        if e["skip"]:
            return "— skip —"
        if not e["labeled"]:
            g = e.get("guess")
            return f"? {g['rank']}{self._SUIT_SYM.get(g['suit'], '?')}" if g else "(unlabeled)"
        return f"{e['rank']}{self._SUIT_SYM.get(e['suit'], '?')}"

    @staticmethod
    def _key_from(path, slot):
        base = os.path.basename(path)
        suf = f"_{slot}.png"
        frame = base[:-len(suf)] if base.endswith(suf) else os.path.splitext(base)[0]
        return f"{frame}#{slot}"

    def _labels_row(self, e, top=False):
        """Insert one library entry as a row (iid = crop path, deduped)."""
        import datetime
        path = e["path"]
        if path and self.labels_tree.exists(path):
            return
        when = datetime.datetime.fromtimestamp(e["mtime"]).strftime("%H:%M:%S")
        txt = self._label_text(e)
        if e["key"] in self._suspects:                # flagged by the kNN check
            txt = "⚠ " + txt
        vals = (when, self._source_of(e["frame"]),
                self._SLOT_HUMAN.get(e["slot"], e["slot"]), txt,
                "✓" if e["reviewed"] else "")
        self.labels_tree.insert("", 0 if top else "end", iid=path, values=vals)
        self._labels_path[path] = path
        self._labels_key[path] = e["key"]

    def _ensure_suspects(self):
        """Compute the kNN label-consistency flags once (cached until the library
        changes). A flag means 'lookalikes disagree' — a card to double-check, not a
        verdict; most are correct-but-ambiguous (9 vs T)."""
        if self._suspect_list is None:
            try:
                self._suspect_list = self._lib.suspect_labels()
            except Exception:                         # noqa: BLE001
                self._suspect_list = []
            self._suspects = {s["key"]: s["suggest"] for s in self._suspect_list}

    def _sorted_entries(self, entries):
        """Order the library list for review per the Sort control."""
        sort = self._sort_var.get()
        if sort == "Hard cases first":
            self._ensure_suspects()
            order = {s["key"]: i for i, s in enumerate(self._suspect_list)}
            return sorted(entries, key=lambda e: (order.get(e["key"], 1 << 30), -e["mtime"]))
        if sort == "By label":                        # twins adjacent -> outliers pop
            ro = {r: i for i, r in enumerate(self._RANKS)}
            return sorted(entries, key=lambda e: (0 if e["labeled"] else 1,
                          ro.get(e["rank"], 99), e["suit"] or "", -e["mtime"]))
        if sort == "By slot":
            return sorted(entries, key=lambda e: (e["slot"], -e["mtime"]))
        return entries                                # Newest (entries() already desc)

    def _reload_labels_list(self, select=None):
        """Rebuild the list from disk in the chosen order. Counts cover the WHOLE
        library; 'Hide reviewed' only filters what's shown. Cheap enough for a
        button / post-edit; not run per-frame."""
        self._lib.reload()
        self._suggest_dirty = True                    # library changed -> rebuild guesser
        for it in self.labels_tree.get_children():
            self.labels_tree.delete(it)
        self._labels_path.clear()
        self._labels_key.clear()
        self._labels_total = self._labels_needs = self._labels_reviewed = 0
        entries = self._lib.entries()
        for e in entries:
            self._labels_total += 1
            if not e["labeled"] and not e["skip"]:
                self._labels_needs += 1
            if e["reviewed"]:
                self._labels_reviewed += 1
        hide = self._hide_reviewed.get()
        for e in self._sorted_entries(entries):
            if not (hide and e["reviewed"]):
                self._labels_row(e, top=False)
        # current session's banks are now in the list; don't let _append re-add them
        s = self._session()
        self._live_seen = len(s["advisor"].banked) if s else 0
        self._update_labels_count()
        if select and self.labels_tree.exists(select):
            self.labels_tree.selection_set(select)
            self.labels_tree.see(select)

    def _update_labels_count(self):
        flagged = f" · {len(self._suspects)} flagged" if self._suspects else ""
        self._labels_count.configure(
            text=f"{self._labels_total} crops · {self._labels_needs} need a label · "
                 f"{self._labels_reviewed} reviewed{flagged}")

    def _select_next_unreviewed(self):
        """Select the first not-yet-reviewed crop currently in view (and preview it)."""
        for iid in self.labels_tree.get_children():
            if not self._lib.labels.get(self._labels_key.get(iid), {}).get("reviewed"):
                self.labels_tree.selection_set(iid)
                self.labels_tree.see(iid)
                self._show_label_crop()
                return
        self._labels_status("no unreviewed crops in view ✓")

    def _show_label_crop(self):
        sel = self.labels_tree.selection()
        if not sel:
            return
        iid = sel[0]
        path = self._labels_path.get(iid)
        if path and os.path.exists(path):
            try:
                img = self.tk.PhotoImage(file=path)   # Tk 8.6 reads PNG natively
                self._labels_img = img
                self._labels_preview.configure(image=img, text="")
            except Exception as ex:                   # noqa: BLE001
                self._labels_img = None
                self._labels_preview.configure(image="", text=f"(can't load: {ex})")
        else:
            self._labels_img = None
            self._labels_preview.configure(image="", text="(crop not on disk)")
        # seed the pickers: from the real label if there is one, else the detector's
        # guess (stored at capture/import time) so an unlabeled crop is one click.
        key = self._labels_key.get(iid)
        lab = self._lib.labels.get(key, {}) if key else {}
        src = lab if "rank" in lab else (lab.get("_guess") or {})
        self._edit_rank.set(src.get("rank", ""))
        self._edit_suit.set(self._SUIT_LETTER.get(src.get("suit", ""), ""))
        if key in self._suspects:
            self._labels_status(f"⚠ lookalike crops are labelled {self._suspects[key]}"
                                " — double-check this one")
        elif "rank" not in lab and lab.get("_guess"):
            g = lab["_guess"]
            self._labels_status(
                f"detector guess {g['rank']}{self._SUIT_SYM.get(g['suit'], '?')}"
                " — verify and Save")

    def _selected_key(self):
        sel = self.labels_tree.selection()
        if not sel:
            self._labels_status("select a crop in the list first", err=True)
            return None, None
        return sel[0], self._labels_key.get(sel[0])

    # ----------------------------------------------------- session resync -----
    def _sync_writer(self):
        """Refresh the live writer's in-memory labels from disk after a tab edit, so
        its next bank (which rewrites the whole file) can't clobber the edit or
        resurrect a deleted entry (the POKER.md gotcha)."""
        s = self._session()
        if s and getattr(s["advisor"], "training", None) is not None:
            try:
                s["advisor"].training.reload()
            except Exception:                         # noqa: BLE001
                pass

    def _sync_after_edit(self):
        """As :meth:`_sync_writer`, plus refit the detector (if asked) so a changed
        label takes effect immediately. Used by edits that alter training data."""
        self._sync_writer()
        s = self._session()
        if s and self._refit_var.get() and getattr(s["advisor"], "card_reader", None):
            try:
                s["advisor"].card_reader.reload()
            except Exception as ex:                    # noqa: BLE001
                self._labels_status(f"refit failed: {ex}", err=True)

    # --------------------------------------------------------------- edits ----
    def _save_label(self):
        iid, key = self._selected_key()
        if not key:
            return
        r, su = self._edit_rank.get(), self._edit_suit.get()
        if not (r and su):
            self._labels_status("pick a rank and a suit", err=True)
            return
        self._lib.reload()                            # pick up any live banks first
        prev = self._lib.labels.get(key, {})
        unchanged = (prev.get("rank") == r
                     and self._SUIT_LETTER.get(prev.get("suit", "")) == su)
        self._lib.set_label(key, r, su)
        self._suspect_list = None                     # labels changed -> recompute flags
        # Saving an unchanged label just confirms it (marks reviewed) — the training
        # set didn't change, so skip the detector refit; only resync the writer.
        self._sync_writer() if unchanged else self._sync_after_edit()
        self._reload_labels_list(select=iid)
        slot = self._SLOT_HUMAN.get(key.split("#")[1])
        self._labels_status(f"{'confirmed' if unchanged else 'labelled'} {slot} = {r}{su}")

    def _mark_reviewed(self):
        """Mark the selected (already-labeled) crop reviewed — 'this label is right' —
        without changing it. Metadata only, so no detector refit; but the writer is
        resynced so the flag survives the next bank's full-file rewrite."""
        iid, key = self._selected_key()
        if not key:
            return
        self._lib.reload()
        if "rank" not in self._lib.labels.get(key, {}):
            self._labels_status("label it first, then mark it reviewed", err=True)
            return
        self._lib.set_reviewed(key)
        self._sync_writer()
        self._reload_labels_list(select=iid)
        self._labels_status(f"marked {self._SLOT_HUMAN.get(key.split('#')[1])} reviewed ✓")

    def _skip_label(self):
        iid, key = self._selected_key()
        if not key:
            return
        self._lib.reload()
        self._lib.set_skip(key)
        self._suspect_list = None
        self._sync_after_edit()
        self._reload_labels_list(select=iid)
        self._labels_status(f"marked {key.split('#')[1]} as skip (excluded from training)")

    def _confirm_delete(self, key):
        """Yes/no guard for a destructive delete. Separated so tests can stub it."""
        from tkinter import messagebox
        return messagebox.askyesno(
            "Delete crop", f"Permanently delete {self._SLOT_HUMAN.get(key.split('#')[1])}"
            "'s crop and label?\nThe PNG is removed from disk.", parent=self.root)

    def _delete_label(self):
        iid, key = self._selected_key()
        if not key:
            return
        if not self._confirm_delete(key):
            self._labels_status("delete cancelled")
            return
        self._lib.reload()
        self._lib.delete(key)
        self._suspect_list = None
        self._sync_after_edit()
        self._reload_labels_list()
        self._labels_img = None
        self._labels_preview.configure(image="", text="(select a crop to preview)")
        self._labels_status(f"deleted {key}")

    def _labels_status(self, msg, err=False):
        self._labels_msg.configure(text=msg, foreground="#a00" if err else "#070")

    def _open_cards_dir(self):
        d = self._root_dir / "data" / "poker_cards"
        try:
            if os.name == "nt":
                os.startfile(str(d))                  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception as e:                        # noqa: BLE001
            self._labels_status(f"can't open folder: {e}", err=True)

    # ----------------------------------------------------- create new crops ---
    def _grab_poker_frame(self):
        """One poker frame + its 'poker' ROIs for capturing crops. Uses the running
        session's grabber if there is one, else a one-shot grab from the configured
        screen. Returns (frame, poker_cfg) or (None, reason)."""
        from .live import load_config, grab_frame, _screen_dimmed
        from ..capture.screen import ScreenGrabber
        s = self._session()
        if s:
            frame, cfg = s["grab_frame"](s["grab"], s["cfg"]), s["cfg"]
        else:
            try:
                cfg = load_config(self._config_path())
            except Exception as e:                    # noqa: BLE001
                return None, f"config error: {e}"
            with ScreenGrabber(monitor=cfg.get("monitor", 1)) as g:
                frame = grab_frame(g, cfg)
        if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
            return None, "Judgment window not found — open it on the poker table"
        if _screen_dimmed(frame):
            return None, "screen is dimmed/paused — resume the game, then capture"
        if not cfg.get("poker"):
            return None, "no 'poker' ROIs in the config (calibrate first)"
        return (frame, cfg["poker"]), None

    def _reader_for_suggest(self):
        """A card reader to pre-fill labels for new crops: the running session's, or
        a one-off built from the library (cached; rebuilt after edits). None if there
        aren't enough labeled exemplars yet."""
        s = self._session()
        if s and getattr(s["advisor"], "card_reader", None) is not None:
            return s["advisor"].card_reader
        if self._suggest_dirty:
            self._suggest_dirty = False
            try:
                from ..vision.poker_cards import HoleCardReader
                self._suggest_reader = HoleCardReader(self._lib.dir)
            except Exception:                         # noqa: BLE001 - too few exemplars
                self._suggest_reader = None
        return self._suggest_reader

    def _guess_for(self, crop, slot):
        """The detector's (rank, suit) guess for a NATIVE crop, or None. Computed at
        capture/import time (native crop -> reliable colour), stored as the pre-fill."""
        reader = self._reader_for_suggest()
        if reader is None:
            return None
        try:
            from ..cards import INT_TO_RANK, INT_TO_SUIT
            (ri, si), _ = reader.recognize(crop, kind=slot[0])
            return INT_TO_RANK[ri], INT_TO_SUIT[si]
        except Exception:                             # noqa: BLE001
            return None

    def _capture_from_game(self):
        """Grab the face-up cards on screen now and add each as a NEW unlabeled crop
        (deduped against the library), pre-filled with the detector's guess and ready
        to verify in the list."""
        from ..vision.poker_cards import whole_card_crops
        got, err = self._grab_poker_frame()
        if err:
            return self._labels_status(err, err=True)
        frame, poker = got
        self._lib.reload()
        n = 0
        for slot, crop in whole_card_crops(frame, poker):
            if self._lib.is_dup(crop):
                continue
            self._cap_seq += 1
            self._lib.add(crop, f"cap{self._cap_pid}_{self._cap_seq}", slot,
                          guess=self._guess_for(crop, slot))
            n += 1
        self._reload_labels_list()
        self._labels_status(
            f"captured {n} new crop(s) — pick a row and label it" if n
            else "nothing new on screen (already in the library)", err=(n == 0))

    def _import_screenshots(self):
        """Pick saved poker FRAMES (full-res, e.g. data/poker) and import their
        face-up cards as unlabeled crops. (Steam screenshots are downscaled and
        won't line up with the ROIs — those yield nothing, by design.)"""
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Import poker frames", initialdir=str(self._root_dir / "data" / "poker"),
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if paths:
            self._import_frames(list(paths))

    def _import_frames(self, paths):
        """Core of import (no dialog, so it's testable): crop each frame's face-up
        slots and add the new, non-duplicate ones as unlabeled crops."""
        import cv2
        from .live import load_config
        from ..vision.poker_cards import whole_card_crops
        try:
            cfg = load_config(self._config_path())
        except Exception as e:                        # noqa: BLE001
            return self._labels_status(f"config error: {e}", err=True)
        poker = cfg.get("poker")
        if not poker:
            return self._labels_status("no 'poker' ROIs in the config", err=True)
        self._lib.reload()
        n = 0
        for p in paths:
            im = cv2.imread(p)
            if im is None:
                continue
            stem = os.path.splitext(os.path.basename(p))[0]
            for slot, crop in whole_card_crops(im, poker):
                if self._lib.is_dup(crop):
                    continue
                self._lib.add(crop, f"imp_{stem}", slot, guess=self._guess_for(crop, slot))
                n += 1
        self._reload_labels_list()
        self._labels_status(
            f"imported {n} new crop(s) — label them in the list" if n
            else "no new cards found (wrong resolution, or already imported)",
            err=(n == 0))
