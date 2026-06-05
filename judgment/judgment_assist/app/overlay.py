"""Always-on-top, borderless suggestion overlay (tkinter, no extra deps).

Shows the advice and — for poker — carries the card-entry box itself, so there's
a single window (no separate console). The live loop drives it through tkinter's
own event loop (``root.after`` + ``mainloop``), so typing stays responsive.

Draggable: click-and-drag the text area to move it (it's borderless, no title
bar). Esc closes it. ``on_submit(text)`` is called when the user presses Enter in
the input box.
"""
from __future__ import annotations


class SuggestionOverlay:
    def __init__(self, x=40, y=40, alpha=0.9, font_size=18,
                 input_enabled=False, hint="", on_submit=None):
        import tkinter as tk
        self._tk = tk
        self.on_submit = on_submit
        self.closed = False
        self.root = tk.Tk()
        # Title must NOT contain "judgment" — the capture layer finds the game
        # window by that substring and would otherwise grab this overlay instead.
        self.root.title("rgg-advisor")
        self.root.overrideredirect(True)             # no title bar / border
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass
        self.root.configure(bg="#101010")
        self.root.geometry(f"+{int(x)}+{int(y)}")

        self.label = tk.Label(
            self.root, text="rgg-advisor ready\n(drag me)", justify="left", anchor="w",
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
            if hint:
                tk.Label(self.root, text=hint, fg="#8a8a8a", bg="#101010",
                         justify="left", anchor="w", font=("Consolas", 9),
                         padx=12).pack(fill="x", pady=(0, 6))
            self.entry.focus_set()
            try:
                self.root.after(50, self.root.focus_force)   # overrideredirect needs a nudge
            except Exception:
                pass

        self._bind_drag()
        self.root.bind("<Escape>", lambda e: self.request_close())
        self.pump()

    def _bind_drag(self):
        """Reposition the borderless window by dragging the text area (not the
        input box, which needs clicks for the cursor)."""
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
        """Ask the loop to stop and exit the mainloop."""
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
