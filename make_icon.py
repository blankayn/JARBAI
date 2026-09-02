"""Generate the JARBAI arc-reactor icon.

Writes jarbai.ico (desktop shortcut) and dashboard/favicon.ico (the app
window's title-bar and taskbar icon). Run once; re-run only to restyle.

    .venv/Scripts/python.exe make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
S = 1024                      # supersampled canvas, downscaled at save time
SIZES = [16, 24, 32, 48, 64, 128, 256]

DISC = (7, 20, 34, 255)
CYAN = (34, 211, 238, 255)
PALE = (125, 227, 243, 255)
WHITE = (240, 253, 255, 255)


def ring(draw, cx, cy, r, width, colour):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=width)


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    g = ImageDraw.Draw(glow)
    c = S / 2

    # dark disc so the mark reads on any wallpaper
    d.ellipse([12, 12, S - 12, S - 12], fill=DISC)
    ring(d, c, c, c - 18, 12, (34, 211, 238, 90))

    # outer containment ring
    ring(d, c, c, S * 0.375, 26, CYAN)
    ring(g, c, c, S * 0.375, 40, CYAN)

    # eight spokes between the rings
    import math
    for i in range(8):
        a = i * math.pi / 4 + math.pi / 8
        x1, y1 = c + math.cos(a) * S * 0.215, c + math.sin(a) * S * 0.215
        x2, y2 = c + math.cos(a) * S * 0.360, c + math.sin(a) * S * 0.360
        d.line([x1, y1, x2, y2], fill=PALE, width=18)
        g.line([x1, y1, x2, y2], fill=CYAN, width=26)

    # inner ring + nucleus
    ring(d, c, c, S * 0.205, 22, PALE)
    ring(g, c, c, S * 0.205, 34, CYAN)
    d.ellipse([c - S * 0.115] * 2 + [c + S * 0.115] * 2, fill=WHITE)
    g.ellipse([c - S * 0.150] * 2 + [c + S * 0.150] * 2, fill=CYAN)

    # bloom
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.030))
    out = Image.alpha_composite(glow, img)

    # keep everything inside the disc
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([8, 8, S - 8, S - 8], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    out.putalpha(Image.composite(out.getchannel("A"), Image.new("L", (S, S), 0), mask))
    return out


def main():
    art = build()
    targets = [ROOT / "jarbai.ico", ROOT / "dashboard" / "favicon.ico"]
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        art.save(path, format="ICO", sizes=[(s, s) for s in SIZES])
        print(f"wrote {path.relative_to(ROOT)}")
    art.resize((512, 512), Image.LANCZOS).save(ROOT / "dashboard" / "icon.png")
    print("wrote dashboard/icon.png")


if __name__ == "__main__":
    main()
