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
    if r > 1:
        return 0.0
    # bright core plus a soft halo
    return min(1.0, 0.75 * math.exp(-((r / 0.28) ** 2) / 2) + 0.45 * (1 - r) ** 2)


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

    def blend(base, layer, pos, size, k_mul):
        """Normal (BLEND) composite, used for the dark underlay."""
        layer = layer.resize(size, Image.LANCZOS)
        px_b, px_l = base.load(), layer.load()
        for j in range(size[1]):
            for i in range(size[0]):
                x, y = pos[0] + i, pos[1] + j
                if 0 <= x < base.width and 0 <= y < base.height:
                    r, g, b, a = px_l[i, j]
                    k = a / 255 * k_mul
                    br, bg_, bb, _ = px_b[x, y]
                    px_b[x, y] = (int(br * (1 - k) + r * k), int(bg_ * (1 - k) + g * k), int(bb * (1 - k) + b * k), 255)

    blue, purple = (51, 128, 255), (255, 77, 217)
    under = (5, 20, 77)
    glow, size = 2.0, 14  # in-game: orb drawn at size * GLOW, underlay at 1.25x that, sparkle at size * 1.9

    def lighten(rgb):
        return tuple(int(c + (255 - c) * 0.25) for c in rgb)

    def curve(t):  # stand-in for the pop-then-home path: up and out, then home to the bar
        x = 40 + 560 * t
        y = 300 - 230 * math.sin(math.pi * min(1.0, t * 1.15)) ** 0.8 * (1 - t) - 20 * t
        return x, y

    # a burst in flight: one orb per slot along the path, rested orbs larger, ghosts at 0.015 steps (in p)
    for k in range(16):
        t = 0.08 + 0.84 * k / 15
        rested = k % 4 == 0
        col = purple if rested else blue
        sz = size * (1.15 if rested else 1.0)
        for g, a, gs in ((2, 0.30, 0.70), (1, 0.55, 0.85), (0, 1.0, 1.0)):
            gx, gy = curve(max(0.0, t - 0.015 * g * 6))  # exaggerated step so the ghosts show at this scale
            gsz = int(sz * glow * gs)
            if g == 0:
                usz = int(sz * glow * 1.25)
                blend(bg, tint(imgs["orb"], under), (int(gx) - usz // 2, int(gy) - usz // 2), (usz, usz), 0.45)
            layer = tint(imgs["orb"], col)
            layer.putalpha(layer.getchannel("A").point(lambda p, a=a: int(p * a)))
            add(bg, layer, (int(gx) - gsz // 2, int(gy) - gsz // 2), (gsz, gsz))
        x, y = curve(t)
        ssz = int(sz * 1.9)
        spark = tint(imgs["sparkle"], lighten(col))
        spark.putalpha(spark.getchannel("A").point(lambda p: int(p * 0.6)))
        add(bg, spark, (int(x) - ssz // 2, int(y) - ssz // 2), (ssz, ssz))
    add(bg, tint(imgs["flash"], blue), (440, 310), (160, 40))
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
