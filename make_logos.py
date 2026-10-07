"""Generate the hex-sticker logos for the ChetaMeck and Plagiarism Check engines.

Run once (``python make_logos.py``); writes PNGs next to this file. Colours come
from the MüCOS logo (teal #009dd1, slate #434553, light cyan #9ed7ea).
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
TEAL, SLATE, CYAN, OFFWHITE = "#009dd1", "#434553", "#9ed7ea", "#e6e2e2"
DARK, AMBER = "#232331", "#ffc93c"
S = 4          # supersampling
W = 512


def font(size, bold=True):
    for name in (("segoeuib.ttf", "seguibl.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(name, size * S)
        except OSError:
            continue
    return ImageFont.load_default()


def hexagon(cx, cy, r):
    return [(cx + r * math.cos(math.radians(60 * i + 30)),
             cy + r * math.sin(math.radians(60 * i + 30))) for i in range(6)]


def tri(cx, cy, size, up):
    h = size * math.sqrt(3) / 2
    if up:
        return [(cx, cy - 2 * h / 3), (cx - size / 2, cy + h / 3),
                (cx + size / 2, cy + h / 3)]
    return [(cx, cy + 2 * h / 3), (cx - size / 2, cy - h / 3),
            (cx + size / 2, cy - h / 3)]


def canvas():
    n = W * S
    return Image.new("RGBA", (n, n), (0, 0, 0, 0)), n


def sticker_base(d, n, fill, border):
    c = n / 2
    r = n * 0.485
    d.polygon(hexagon(c, c, r), fill=border)
    d.polygon(hexagon(c, c, r * 0.90), fill=fill)
    return c, r


def centered(d, text, y, f, fill, n):
    box = d.textbbox((0, 0), text, font=f)
    d.text(((n - (box[2] - box[0])) / 2 - box[0], y), text, font=f, fill=fill)


def chetameck():
    im, n = canvas()
    d = ImageDraw.Draw(im)
    sticker_base(d, n, DARK, TEAL)
    # MuCOS-like triangles: three teal down-triangles, two slate up-triangles
    size = n * 0.19
    h = size * math.sqrt(3) / 2
    ty = n * 0.28
    cx = n / 2
    d.polygon(tri(cx, ty, size, False), fill=TEAL)
    d.polygon(tri(cx - size / 2, ty + h, size, False), fill=TEAL)
    d.polygon(tri(cx + size / 2, ty + h, size, False), fill=TEAL)
    d.polygon(tri(cx - size / 2, ty + h / 3, size, True), fill=SLATE)
    d.polygon(tri(cx + size / 2, ty + h / 3, size, True), fill=SLATE)
    centered(d, "CHETA", n * 0.585, font(60), OFFWHITE, n)
    centered(d, "MECK", n * 0.69, font(60), CYAN, n)
    return im.resize((W, W), Image.LANCZOS)


def plagiarism():
    im, n = canvas()
    d = ImageDraw.Draw(im)
    sticker_base(d, n, DARK, AMBER)

    def page(x, y, w, h, hits):
        d.rounded_rectangle((x, y, x + w, y + h), radius=n * 0.02, fill=OFFWHITE,
                            outline=SLATE, width=int(n * 0.006))
        lh = h / 8.0
        for i in range(6):
            yy = y + lh * (i + 0.9)
            col = AMBER if i in hits else "#a9a9bd"
            d.rounded_rectangle((x + w * 0.12, yy, x + w * 0.88, yy + lh * 0.38),
                                radius=lh * 0.18, fill=col)

    page(n * 0.22, n * 0.15, n * 0.30, n * 0.38, {1, 2, 4})
    page(n * 0.42, n * 0.22, n * 0.30, n * 0.38, {2, 3, 4})
    mx, my, mr = n * 0.62, n * 0.45, n * 0.085
    d.ellipse((mx - mr, my - mr, mx + mr, my + mr), outline=TEAL,
              width=int(n * 0.026), fill=(158, 215, 234, 90))
    a = math.radians(45)
    d.line((mx + mr * math.cos(a), my + mr * math.sin(a),
            mx + mr * 2.0 * math.cos(a), my + mr * 2.0 * math.sin(a)),
           fill=TEAL, width=int(n * 0.036))
    centered(d, "PLAGIARISM", n * 0.64, font(42), OFFWHITE, n)
    centered(d, "CHECK", n * 0.725, font(42), AMBER, n)
    return im.resize((W, W), Image.LANCZOS)


def save(img, name, small=88):
    img.save(HERE / f"{name}.png")
    img.resize((small, small), Image.LANCZOS).save(HERE / f"{name}_small.png")


if __name__ == "__main__":
    save(chetameck(), "chetameck_logo")
    save(plagiarism(), "plagcheck_logo")
    print("logos written")
