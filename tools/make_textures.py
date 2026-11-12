"""Generate XPOrbs media (white RGBA, tinted in-game with SetVertexColor).

Run: uv run --with pillow python tools/make_textures.py [--preview]
Writes uncompressed 32-bit TGA files with a bottom-left origin to media/.
"""

import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
PREVIEW = ROOT / "tools" / "preview"


def build(size, alpha_fn):
    w, h = size
    img = Image.new("RGBA", size, (255, 255, 255, 0))
    px = img.load()
    for j in range(h):
        for i in range(w):
            u = (i + 0.5) / w * 2 - 1  # -1..1
            v = (j + 0.5) / h * 2 - 1
            a = max(0.0, min(1.0, alpha_fn(u, v)))
            px[i, j] = (255, 255, 255, int(round(a * 255)))
    return img


def orb(u, v):
    r = math.hypot(u, v)
    return (1 - r) ** 2 if r < 1 else 0.0


def sparkle(u, v):
    r = math.hypot(u, v)
    if r >= 1:
        return 0.0
    fall = (1 - r) ** 1.5
    streak_h = math.exp(-((v / 0.07) ** 2) / 2) * (1 - abs(u)) ** 1.5
    streak_v = math.exp(-((u / 0.07) ** 2) / 2) * (1 - abs(v)) ** 1.5
    core = math.exp(-((r / 0.16) ** 2) / 2)
    return min(1.0, streak_h + streak_v + core * 0.9) * (0.35 + 0.65 * fall) if r < 1 else 0.0


def flash(u, v):
    r = math.hypot(u, v)  # u, v already normalised per axis -> elliptical
    return (1 - r) ** 1.5 if r < 1 else 0.0


def save_tga(img, path):
    # Pillow writes uncompressed 32-bit TGA, bottom-left origin by default (orientation=1).
    img.save(path, format="TGA", compression=None)


def preview(imgs):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    bg = Image.new("RGBA", (640, 360), (14, 18, 30, 255))
    # tinted sheet: blue orb, purple orb, sparkle, flash
    def tint(img, rgb):
        out = Image.new("RGBA", img.size, rgb + (0,))
        out.putalpha(img.getchannel("A"))
        return out

    def add(base, layer, pos, size):
        layer = layer.resize(size, Image.LANCZOS)
        px_b, px_l = base.load(), layer.load()
        for j in range(size[1]):
            for i in range(size[0]):
                x, y = pos[0] + i, pos[1] + j
                if 0 <= x < base.width and 0 <= y < base.height:
                    r, g, b, a = px_l[i, j]
                    br, bg_, bb, ba = px_b[x, y]
                    k = a / 255
                    px_b[x, y] = (min(255, int(br + r * k)), min(255, int(bg_ + g * k)), min(255, int(bb + b * k)), 255)

    blue, purple = (89, 166, 255), (179, 115, 255)
    # an arc of orbs with ghosts, ~ a burst in flight, at in-game-ish size (28px glow for size 14)
    for k in range(14):
        t = k / 13
        x = 40 + 520 * t
        y = 280 - 200 * math.sin(math.pi * t * 0.85) - 30 * t
        col = purple if k % 4 == 0 else blue
        for g, a in ((2, 0.25), (1, 0.5), (0, 1.0)):
            gt = max(0, t - 0.03 * g)
            gx = 40 + 520 * gt
            gy = 280 - 200 * math.sin(math.pi * gt * 0.85) - 30 * gt
            layer = tint(imgs["orb"], col)
            layer.putalpha(layer.getchannel("A").point(lambda p, a=a: int(p * a)))
            add(bg, layer, (int(gx) - 16, int(gy) - 16), (32, 32))
        add(bg, tint(imgs["sparkle"], (200, 225, 255)), (int(x) - 22, int(y) - 22), (44, 44))
    add(bg, tint(imgs["flash"], blue), (440, 300), (160, 40))
    # large raw sheet
    sheet = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    out = bg.copy()
    add(out, tint(imgs["orb"], blue), (20, 20), (96, 96))
    add(out, tint(imgs["sparkle"], blue), (130, 20), (96, 96))
    add(out, tint(imgs["flash"], blue), (240, 40), (192, 48))
    del sheet
    out.convert("RGB").save(PREVIEW / "preview.png")


def main():
    MEDIA.mkdir(exist_ok=True)
    imgs = {
        "orb": build((64, 64), orb),
        "sparkle": build((64, 64), sparkle),
        "flash": build((128, 32), flash),
    }
    for name, img in imgs.items():
        save_tga(img, MEDIA / f"{name}.tga")
        print(f"wrote media/{name}.tga {img.size}")
    if "--preview" in sys.argv:
        preview(imgs)
        print(f"wrote {PREVIEW / 'preview.png'}")


if __name__ == "__main__":
    main()
