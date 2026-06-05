"""Always-on-top suggestion overlay (tkinter, no extra deps).

Two modes:
* **Display-only** (``input_enabled=False``, the usual case now that corrections
  live in the launcher): a clean *borderless* floating box, drag it anywhere; its
  lifecycle is managed by whoever created it.
* **With input** (``input_enabled=True``, the standalone CLI poker path where you
  type cards into the overlay): a normal *titled* window so it has a close button
  and standard keyboard focus. ``on_submit(text)`` fires on Enter; Esc clears the
  box (never quits).
"""
from __future__ import annotations


class SuggestionOverlay:
    def __init__(self, x=40, y=40, alpha=0.92, font_size=18,
                 input_enabled=False, hint="", on_submit=None, master=None):
        import tkinter as tk
        self._tk = tk
        self.on_submit = on_submit
        self.closed = False
        # A child Toplevel when run inside another tk app (e.g. the launcher), else
        # its own root for the standalone CLI.
        self.root = tk.Toplevel(master) if master is not None else tk.Tk()
        # Title must NOT contain "judgment" — the capture layer finds the game
        # window by that substring and would otherwise grab this overlay instead.
        self.root.title("rgg-advisor")
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass
        self.root.configure(bg="#101010")
        self.root.geometry(f"+{int(x)}+{int(y)}")
        if input_enabled:
            self.root.resizable(False, False)
            self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        else:
            self.root.overrideredirect(True)    # borderless: just an overlay

        self.label = tk.Label(
            self.root, text="rgg-advisor ready", justify="left", anchor="w",
            fg="#39ff14", bg="#101010", font=("Consolas", font_size, "bold"),
            padx=12, pady=8,
        )
        self.label.pack(fill="both", expand=True)

        self.entry = None
        if input_enabled:
            self.entry = tk.Entry(self.root, bg="#1c1c1c", fg="#ffffff",
                                  insertbackground="#39ff14", relief="flat",
                                  font=("Consolas", max(10, font_size - 4)))
            self.entry.pack(fill="x", padx=12, pady=(0, 4))
            self.entry.bind("<Return>", self._submit)
            self.entry.bind("<Escape>", self._cancel)
            if hint:
                tk.Label(self.root, text=hint, fg="#8a8a8a", bg="#101010",
                         justify="left", anchor="w", font=("Consolas", 9),
                         padx=12).pack(fill="x", pady=(0, 6))
        else:
            self._bind_drag()                   # no title bar -> drag the box itself
        self.pump()

    def _bind_drag(self):
        """Reposition the borderless window by dragging the text area."""
        self._drag = (0, 0)

        def press(e):
            self._drag = (e.x, e.y)

        def move(e):
            dx, dy = self._drag
            self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

        for w in (self.root, self.label):
            w.bind("<Button-1>", press)
            w.bind("<B1-Motion>", move)

    def _submit(self, _event):
        text = self.entry.get()
        self.entry.delete(0, "end")
        if self.on_submit is not None:
            self.on_submit(text)

    def _cancel(self, _event):
        self.entry.delete(0, "end")
        return "break"

    def update_text(self, text):
        """Set the advice text. Drawing is handled by the running mainloop."""
        self.label.config(text=text)

    def pump(self):
        """Process pending GUI events (used before the mainloop starts)."""
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def request_close(self):
        """Ask the loop to stop and exit the mainloop (title-bar X or typed 'q')."""
        self.closed = True
        try:
            self.root.quit()
        except Exception:
            pass

    def close(self):
        self.closed = True
        try:
            self.root.destroy()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
