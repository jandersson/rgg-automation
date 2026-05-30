"""Always-on-top, borderless suggestion overlay (tkinter, no extra deps).

Driven by a polling loop rather than tkinter's mainloop: call ``update_text``
each frame and ``pump`` to keep the window responsive.

Draggable: click-and-drag anywhere on the box to move it (it's borderless, so
there's no title bar to grab). Position is also settable via the constructor.
"""
from __future__ import annotations


class SuggestionOverlay:
    def __init__(self, x=40, y=40, alpha=0.85, font_size=18):
        import tkinter as tk
        self._tk = tk
        self.root = tk.Tk()
        self.root.title("judgment-assist")
        self.root.overrideredirect(True)             # no title bar / border
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass
        self.root.configure(bg="#101010")
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self.label = tk.Label(
            self.root, text="judgment-assist ready\n(drag me)", justify="left", anchor="w",
            fg="#39ff14", bg="#101010", font=("Consolas", font_size, "bold"),
            padx=12, pady=8,
        )
        self.label.pack(fill="both", expand=True)
        self._bind_drag()
        self.pump()

    def _bind_drag(self):
        """Let the user reposition the borderless window by dragging it."""
        self._drag = (0, 0)

        def press(e):
            self._drag = (e.x, e.y)

        def move(e):
            dx, dy = self._drag
            self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

        for w in (self.root, self.label):
            w.bind("<Button-1>", press)
            w.bind("<B1-Motion>", move)

    def update_text(self, text):
        self.label.config(text=text)
        self.pump()

    def pump(self):
        """Process pending GUI events without blocking the capture loop."""
        self.root.update_idletasks()
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
