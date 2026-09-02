import math
import tkinter as tk


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v))) for v in rgb))


def mix(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


STATES = {
    "idle":      {"color": "#22d3ee", "label": "online",     "speed": 0.35, "amp": 0.10, "spin": 0.08},
    "listening": {"color": "#22d3ee", "label": "listening",  "speed": 2.0,  "amp": 0.28, "spin": 0.60},
    "thinking":  {"color": "#a78bfa", "label": "processing", "speed": 1.8,  "amp": 0.30, "spin": 2.20},
    "speaking":  {"color": "#fbbf24", "label": "speaking",   "speed": 1.2,  "amp": 0.35, "spin": 0.00},
    "error":     {"color": "#ef4444", "label": "error",      "speed": 3.0,  "amp": 0.38, "spin": 0.00},
}


class Reactor(tk.Canvas):
    """Pulsing glass-like core. Cyan = idle, violet = thinking, gold = speaking."""

    DT = 0.033

    def __init__(self, parent, size=170, bg="#1b2733", **kwargs):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, **kwargs)
        self.size = size
        self.bg = bg
        self.state = "idle"
        self.phase = 0.0
        self.spin = 0.0
        self._running = True
        self.current = list(_hex_to_rgb(STATES["idle"]["color"]))
        self.bind("<Destroy>", self._stop)
        self.after(33, self._tick)

    def set_state(self, state):
        if state in STATES:
            self.state = state

    def _stop(self, _event=None):
        self._running = False

    def _tick(self):
        if not self._running:
            return
        try:
            cfg = STATES[self.state]
            target = _hex_to_rgb(cfg["color"])
            for i in range(3):
                self.current[i] += (target[i] - self.current[i]) * 0.12
            color = _rgb_to_hex(self.current)
            self.phase += cfg["speed"] * self.DT
            self.spin = (self.spin + cfg["spin"]) % 360
            intensity = 0.70 + cfg["amp"] * (0.5 + 0.5 * math.sin(2 * math.pi * self.phase))
            self._draw(color, intensity)
        except tk.TclError:
            self._running = False
            return
        self.after(33, self._tick)

    def _draw(self, color, intensity):
        self.delete("all")
        cx = cy = self.size / 2
        core_r = self.size * 0.20
        glow_max = self.size * 0.47
        outer = core_r + (glow_max - core_r) * intensity

        self.create_oval(cx - glow_max, cy - glow_max, cx + glow_max, cy + glow_max,
                         outline=mix(self.bg, color, 0.12), width=1)

        rings = 22
        for i in range(rings, -1, -1):
            frac = i / rings
            r = core_r + (outer - core_r) * frac
            fill = mix(self.bg, color, (1 - frac) ** 2)
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")

        r_seg = core_r * 2.0
        for k in range(3):
            self.create_arc(cx - r_seg, cy - r_seg, cx + r_seg, cy + r_seg,
                            start=self.spin + k * 120, extent=42,
                            style="arc", outline=mix(self.bg, color, 0.55), width=2)
        r_seg2 = core_r * 1.5
        for k in range(3):
            self.create_arc(cx - r_seg2, cy - r_seg2, cx + r_seg2, cy + r_seg2,
                            start=-self.spin * 1.4 + 60 + k * 120, extent=20,
                            style="arc", outline=mix(self.bg, color, 0.35), width=1)

        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r,
                         fill=mix(color, "#ffffff", 0.08 + 0.22 * intensity),
                         outline=mix(color, "#ffffff", 0.40), width=1)

        hot_r = core_r * 0.62
        self.create_oval(cx - hot_r, cy - hot_r, cx + hot_r, cy + hot_r,
                         fill=mix(color, "#ffffff", 0.45 + 0.25 * intensity), outline="")

        self.create_oval(cx - core_r * 0.60, cy - core_r * 0.75,
                         cx - core_r * 0.15, cy - core_r * 0.30,
                         fill="#ffffff", stipple="gray25", outline="")
