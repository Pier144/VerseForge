"""Images of the custom installer look (installer/style/): wizard background, side panel and corner logo.

    python tools/installer_art.py

Dark navy like the app's dark mode, the cyan diamond of the logo drawn as vectors (sharp at every size) and the
viewer's floor grid in perspective at the bottom. Several sizes of each image: Inno Setup picks the one for the
screen's DPI.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "installer", "style")
BG_TOP, BG_BOTTOM = (10, 16, 23), (13, 27, 40)
FACETS = [(64, 195, 255), (144, 224, 255), (22, 95, 134), (32, 138, 184)]   # top-left, top-right, bottom-left, bottom-right
EDGE = (220, 245, 255)
GRID = (40, 130, 180)


def diamond(size, glow=True):
    """The logo's diamond on a transparent square of `size` px (4 facets, bright edge, soft glow)."""
    s = size * 4                                           # drawn large, then reduced: smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    c, r = s / 2, s * 0.36
    top, right, bottom, left, mid = (c, c - r * 1.07), (c + r, c), (c, c + r * 1.07), (c - r, c), (c, c)
    d = ImageDraw.Draw(img)
    for pts, col in zip(([left, top, mid], [top, right, mid], [left, mid, bottom], [mid, right, bottom]), FACETS):
        d.polygon(pts, fill=col + (255,))
    d.line([top, right, bottom, left, top], fill=EDGE + (255,), width=max(2, s // 90), joint="curve")
    if glow:
        halo = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(halo).polygon([top, right, bottom, left], fill=(80, 200, 255, 150))
        halo = halo.filter(ImageFilter.GaussianBlur(s * 0.06))
        img = Image.alpha_composite(halo, img)
    return img.resize((size, size), Image.LANCZOS)


def background(w, h):
    """Whole-window background: vertical gradient, a faint cyan glow, the floor grid fading towards the horizon."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        col = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = col
    img = img.convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-w * 0.25, h * 0.55, w * 0.55, h * 1.35), fill=(30, 140, 210, 70))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(w * 0.08)))
    # perspective grid on the bottom third
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    horizon, vx = h * 0.66, w * 0.5
    lw = max(1, round(w / 900))
    for i in range(-40, 41):                                    # lines towards the vanishing point
        x_bottom = vx + i * w * 0.09
        g.line([(vx + (x_bottom - vx) * 0.02, horizon), (x_bottom, h)], fill=GRID + (70,), width=lw)
    for k in range(1, 14):                                      # cross lines, closer together near the horizon
        y = horizon + (h - horizon) * (k / 13) ** 2.2
        g.line([(0, y), (w, y)], fill=GRID + (int(25 + 55 * k / 13),), width=lw)
    fade = Image.new("L", (w, h), 0)                            # the grid fades in from the horizon
    fd = ImageDraw.Draw(fade)
    for y in range(int(horizon), h):
        fd.line([(0, y), (w, y)], fill=int(255 * min(1, (y - horizon) / (h - horizon) * 1.6)))
    grid.putalpha(Image.composite(grid.getchannel("A"), Image.new("L", (w, h), 0), fade))
    img = Image.alpha_composite(img, grid)
    return img.convert("RGB")


def side_panel(w, h):
    """Left panel of the first and last page: the diamond, the name and a thin line, on transparency."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dsize = int(w * 0.78)
    dm = diamond(dsize)
    img.alpha_composite(dm, ((w - dsize) // 2, int(h * 0.20)))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("segoeuisl.ttf", int(w * 0.135))
    except OSError:
        font = ImageFont.truetype("arial.ttf", int(w * 0.135))
    text = "VerseForge"
    tw = d.textlength(text, font=font)
    ty = int(h * 0.20) + dsize + int(h * 0.02)
    d.text(((w - tw) / 2, ty), text, font=font, fill=(225, 243, 255, 255))
    ly = ty + int(w * 0.21)
    d.line([(w * 0.28, ly), (w * 0.72, ly)], fill=(64, 195, 255, 200), width=max(1, w // 120))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    # sizes: 100 % DPI first, then 125/150/200 % (the wizard is 120 % of Inno's base size, see WizardSizePercent)
    for scale in (1, 1.25, 1.5, 2):
        tag = int(scale * 100)
        background(round(600 * scale), round(460 * scale)).save(os.path.join(OUT, f"back-{tag}.png"))
        side_panel(round(202 * scale), round(386 * scale)).save(os.path.join(OUT, f"side-{tag}.png"))
        diamond(round(58 * scale)).save(os.path.join(OUT, f"logo-{tag}.png"))
    print("images in", OUT)


if __name__ == "__main__":
    main()
