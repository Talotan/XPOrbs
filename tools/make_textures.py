"""Generate XPOrbs media (white RGBA, tinted in-game with SetVertexColor).

Run: uv run --with pillow python tools/make_textures.py [--preview]
Writes uncompressed 32-bit TGA files with a bottom-left origin to media/.
"""

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

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

# ---------------------------------------------------------------------------
# Orb shapes besides Starlight: Retro (pixel art), Wisp (solid ball), Power (core plus crackling bolts).
# Every new texture has power-of-two dimensions (older clients show other sizes as missing); art that is not
# a power of two is padded and the game crops it with SetTexCoord.
# ---------------------------------------------------------------------------


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def wisp(u, v):
    """Glowing ball: a hot centred core on a solid plateau, a faint bright rim and a soft halo."""
    r = math.hypot(u, v)
    body = 0.72 * (1 - smoothstep(0.52, 0.74, r))
    core = 0.28 * math.exp(-((r / 0.26) ** 2) / 2)
    rim = 0.10 * math.exp(-(((r - 0.60) / 0.06) ** 2) / 2)
    halo = 0.16 * (1 - smoothstep(0.55, 1.0, r))
    return max(halo, body + core + rim)


def wisp_under(u, v):
    """The dark disc under a wisp: solid, with a soft edge."""
    return 1 - smoothstep(0.60, 0.82, math.hypot(u, v))


def power_core(u, v):
    r = math.hypot(u, v)
    return min(1.0, math.exp(-((r / 0.20) ** 2) / 2) + 0.55 * (1 - smoothstep(0.0, 0.62, r)) ** 1.5)


def polar(r, a):
    return (r * math.cos(a), r * math.sin(a))


def bolt_ring(seed, n_arcs, spike, size=64, ss=4, width=2.6, glow_sigma=2.0, sharp_sigma=0.45):
    """A crackling shell: zig-zag arcs of straight segments hugging the core, plus an optional short outward spike.
    Nothing radiates from the centre, so it can't read as legs. Deterministic per seed; stays inside r < 0.92."""
    rnd = random.Random(seed)
    n = size * ss
    core = Image.new("L", (n, n), 0)
    draw = ImageDraw.Draw(core)

    def px(p):
        return ((p[0] + 1) / 2 * n, (p[1] + 1) / 2 * n)

    def stroke(points, w):
        draw.line([px(p) for p in points], fill=255, width=max(1, round(w * ss)), joint="curve")

    base = rnd.uniform(0, 2 * math.pi)
    for k in range(n_arcs):
        a0 = base + 2 * math.pi * k / n_arcs + rnd.uniform(-0.3, 0.3)
        sweep = rnd.uniform(1.2, 2.3)
        segs = rnd.randint(6, 8)
        radius = rnd.uniform(0.44, 0.58)
        sign = rnd.choice([-1, 1])
        points = []
        for i in range(segs + 1):
            a = a0 + sweep * i / segs + rnd.uniform(-0.08, 0.08)
            if rnd.random() < 0.25:  # now and then the zig-zag skips its alternation, so it never reads as a spring
                sign = rnd.choice([-1, 1])
            else:
                sign = -sign
            rad = radius + sign * 0.09 * rnd.uniform(0.3, 1.3)
            if i in (0, segs):
                rad = radius - 0.045  # the ends tuck in towards the core
            points.append(polar(rad, a))
        stroke(points, width)
    for _ in range(spike):
        a = base + rnd.uniform(0, 2 * math.pi)
        stroke([polar(0.36, a), polar(0.52, a + 0.25), polar(0.58, a - 0.05), polar(0.76, a + 0.2)], width * 0.8)
    sharp = core.filter(ImageFilter.GaussianBlur(ss * sharp_sigma))
    glow = core.filter(ImageFilter.GaussianBlur(ss * glow_sigma))  # glow gain 1.0
    alpha = ImageChops.lighter(sharp, glow).resize((size, size), Image.Resampling.LANCZOS)
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    img.putalpha(alpha)
    return img


# Retro art: cells of CELL px. The octagon is 8 x 8 cells; row r lights columns a..b inclusive (corners cut).
CELL = 8
OCTAGON_ROWS = [(2, 5), (1, 6), (0, 7), (0, 7), (0, 7), (0, 7), (1, 6), (2, 5)]
OCTAGON = {(c, r) for r, (a, b) in enumerate(OCTAGON_ROWS) for c in range(a, b + 1)}


def cell_image(cells, canvas):
    """cells {(col, row): alpha} -> white RGBA of canvas px (a power of two), CELL px per cell, art in the top left."""
    img = Image.new("RGBA", (canvas, canvas), (255, 255, 255, 0))
    for (c, r), a in cells.items():
        img.paste((255, 255, 255, round(a * 255)), (c * CELL, r * CELL, (c + 1) * CELL, (r + 1) * CELL))
    return img


def retro():
    """The 8 x 8 cell orb: an octagon in three alpha rings, with two bright shine cells top left."""
    cells = {}
    for c, r in OCTAGON:
        dx, dy = c - 3.5, r - 3.5
        if max(abs(dx), abs(dy)) <= 1.5:
            cells[(c, r)] = 0.80  # core
        elif math.hypot(dx, dy) < 3.2:
            cells[(c, r)] = 0.60  # ring
        else:
            cells[(c, r)] = 0.35  # outer
    cells[(2, 2)] = cells[(3, 2)] = 1.0  # shine
    return cell_image(cells, 64)


def retro_under():
    """The octagon grown by one cell all round (4-neighbour dilation) on a 10 x 10 grid, solid. 128 px, art 80 px."""
    inner = {(c + 1, r + 1) for c, r in OCTAGON}
    grown = set(inner)
    for c, r in inner:
        grown |= {(c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)}
    return cell_image({cell: 1.0 for cell in grown}, 128)


def retro_twinkle():
    """A 3 x 3 cell "+" (centre 1.0, arms 0.55). 32 px, art 24 px."""
    cells = {(1, 1): 1.0}
    cells.update({(0, 1): 0.55, (2, 1): 0.55, (1, 0): 0.55, (1, 2): 0.55})
    return cell_image(cells, 32)


def preview(imgs):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    bg = Image.new("RGBA", (640, 360), (14, 18, 30, 255))
    # tinted sheet: blue orb, purple orb, sparkle, flash
    def tint(img, rgb):
        out = Image.new("RGBA", img.size, rgb + (0,))
        out.putalpha(img.getchannel("A"))
        return out

    def add(base, layer, pos, size):
        layer = layer.resize(size, Image.Resampling.LANCZOS)
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
        layer = layer.resize(size, Image.Resampling.LANCZOS)
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


# --- shape preview sheet: the four shapes with the in-game parameters (Orbs.lua / Shapes.lua) ---------------------------

SIZE = 14  # db.size
PURPLE, BLUE = (0.72, 0.28, 1.0), (0.15, 0.38, 1.0)


def lighten(col, k):
    return tuple(c + (1 - c) * k for c in col)


def _alpha_layer(alpha, size, amul, nearest=False, rot=0.0):
    size = max(1, round(size))
    if rot:
        alpha = alpha.rotate(rot, Image.Resampling.BICUBIC)
    resample = Image.Resampling.NEAREST if nearest else Image.Resampling.LANCZOS
    return alpha.resize((size, size), resample).point(lambda p: int(p * amul))


def _box(cx, cy, size):
    x0, y0 = round(cx - size / 2), round(cy - size / 2)
    return (x0, y0, x0 + size, y0 + size)


def add_layer(canvas, alpha, col, cx, cy, size, amul=1.0, nearest=False, rot=0.0):
    """ADD blend: dst += colour * alpha."""
    a = _alpha_layer(alpha, size, amul, nearest, rot)
    box = _box(cx, cy, a.width)
    layer = Image.merge("RGB", [a.point(lambda p, c=c: int(p * c)) for c in col])
    canvas.paste(ImageChops.add(canvas.crop(box), layer), box[:2])


def blend_layer(canvas, alpha, col, cx, cy, size, amul=1.0, nearest=False):
    """BLEND: dst = dst * (1 - alpha) + colour * alpha."""
    a = _alpha_layer(alpha, size, amul, nearest)
    box = _box(cx, cy, a.width)
    solid = Image.new("RGB", a.size, tuple(round(c * 255) for c in col))
    canvas.paste(Image.composite(solid, canvas.crop(box), a), box[:2])


def add_square(canvas, col, cx, cy, size, amul):
    box = _box(cx, cy, size)
    solid = Image.new("RGB", (size, size), tuple(round(c * 255 * amul) for c in col))
    canvas.paste(ImageChops.add(canvas.crop(box), solid), box[:2])


def _alphas(imgs):
    return {name: img.getchannel("A") for name, img in imgs.items()}


def draw_orb(canvas, kind, tex, col, x, y, ux, uy, t, rnd, trail=True):
    """One orb at (x, y) flying along (ux, uy) at time t, drawn the way the game composites it."""
    dim = tuple(c * 0.25 for c in col)
    if kind == "Starlight":
        body = SIZE * 2.0
        if trail:
            for gap, a, s in ((24, 0.30, 0.70), (12, 0.55, 0.85)):
                add_layer(canvas, tex["orb"], col, x - ux * gap, y - uy * gap, body * s, a)
        blend_layer(canvas, tex["orb"], dim, x, y, body * 1.25, 0.45)
        add_layer(canvas, tex["orb"], col, x, y, body)
        add_layer(canvas, tex["sparkle"], lighten(col, 0.15), x, y, SIZE * 1.9, 0.6, rot=math.degrees(t * 2 * math.pi))
    elif kind == "Retro":
        cell = max(2, math.floor(SIZE * 24 / 14 / 8 + 0.5))

        def snap(v):
            return math.floor(v / cell + 0.5) * cell

        gx, gy = snap(x), snap(y)
        if trail:  # two plain squares: 2 x 2 cells 6 cells behind, 1 cell 10 cells behind
            add_square(canvas, col, snap(x - ux * 6 * cell), snap(y - uy * 6 * cell), 2 * cell, 0.70)
            sx = (math.floor((x - ux * 10 * cell) / cell) + 0.5) * cell
            sy = (math.floor((y - uy * 10 * cell) / cell) + 0.5) * cell
            add_square(canvas, col, sx, sy, cell, 0.40)
        under = tex["retro_under"].crop((0, 0, 80, 80))
        blend_layer(canvas, under, dim, gx, gy, 10 * cell, 0.9, True)
        add_layer(canvas, tex["retro"], col, gx, gy, 8 * cell, 1.0, True)
        if (t + 0.1) % 0.5 < 0.25:  # the twinkle blinks 0.25 s on, 0.25 s off
            twinkle = tex["retro_twinkle"].crop((0, 0, 24, 24))
            add_layer(canvas, twinkle, lighten(col, 0.5), gx - 2.5 * cell, gy - 2.5 * cell, 3 * cell, 1.0, True)
    elif kind == "Wisp":
        body = SIZE * 1.6 * 1.5 * (1 + 0.06 * math.sin(2 * math.pi * 2.5 * t))
        if trail:
            for gap, a, s in ((40, 0.12, 0.55), (30, 0.22, 0.65), (20, 0.36, 0.75), (10, 0.52, 0.87)):
                add_layer(canvas, tex["wisp"], col, x - ux * gap, y - uy * gap, body * s, a)
        blend_layer(canvas, tex["wisp_under"], dim, x, y, body, 0.80)
        add_layer(canvas, tex["wisp"], col, x, y, body)
    else:  # Power
        body = SIZE * 2.0
        if trail:
            for gap, a, s in ((20, 0.30, 0.70), (10, 0.55, 0.85)):
                add_layer(canvas, tex["power_core"], col, x - ux * gap, y - uy * gap, body * s, a)
        blend_layer(canvas, tex["orb"], dim, x, y, body * 1.6, 0.58)
        add_layer(canvas, tex["power_core"], col, x, y, body * 0.9)
        bolt = tex[f"bolt{rnd.randint(1, 4)}"]
        add_layer(
            canvas, bolt, lighten(col, 0.15), x, y, body * 1.5, rnd.uniform(0.7, 1.0), rot=rnd.uniform(0, 360)
        )


def _background(kind, w, h, seed):
    if kind == "dark":
        return Image.new("RGB", (w, h), (14, 18, 30))
    noise = Image.effect_noise((w, h), 40).convert("RGB")  # mid-grey noise: lumpy grass
    return Image.blend(Image.new("RGB", (w, h), (104, 148, 66)), noise, 0.12)


def preview_shapes(imgs):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    tex = _alphas(imgs)
    kinds = ["Starlight", "Retro", "Wisp", "Power"]
    pw, ph = 380, 150
    sheet = Image.new("RGB", (2 * pw + 30, 4 * (ph + 22) + 20 + 150), (30, 30, 36))
    draw = ImageDraw.Draw(sheet)
    for row, kind in enumerate(kinds):
        for col_i, bg_kind in enumerate(["dark", "grass"]):
            rnd = random.Random(row * 2 + col_i)
            panel = _background(bg_kind, pw, ph, row)
            for i in range(12):  # 12 orbs, every one heading somewhere between right and up-right
                ang = rnd.uniform(-0.6, 0.6)
                ux, uy = math.cos(ang), -math.sin(ang)
                x, y = 40 + (i % 6) * 58 + rnd.uniform(-8, 8), 38 + (i // 6) * 70 + rnd.uniform(-10, 10)
                col = PURPLE if i % 4 == 0 else BLUE
                draw_orb(panel, kind, tex, col, x, y, ux, uy, rnd.uniform(0, 2), rnd)
            x0, y0 = 10 + col_i * (pw + 10), 10 + row * (ph + 22) + 16
            sheet.paste(panel, (x0, y0))
            label = f"{kind} / {bg_kind}" + (" (12 shown; the game draws half)" if kind == "Wisp" else "")
            draw.text((x0, y0 - 14), label, fill=(210, 210, 215))
    # ten consecutive ticks of one Power orb (a tick is 70-90 ms): the bolt changes frame, angle and brightness
    y0 = 10 + 4 * (ph + 22) + 16
    draw.text((10, y0 - 14), "Power: ten bolt ticks", fill=(210, 210, 215))
    rnd = random.Random(99)
    frame, turn = 1, 0.0
    for i in range(10):
        cell = _background("dark", 70, 110, 0)
        frame = (frame + rnd.randint(0, 2)) % 4 + 1  # never the same frame twice running
        turn += rnd.uniform(60, 300)
        bolt = tex[f"bolt{frame}"]
        body = SIZE * 2.0
        blend_layer(cell, tex["orb"], tuple(c * 0.25 for c in BLUE), 35, 55, body * 1.6, 0.58)
        add_layer(cell, tex["power_core"], BLUE, 35, 55, body * 0.9)
        add_layer(cell, bolt, lighten(BLUE, 0.15), 35, 55, body * 1.5, rnd.uniform(0.7, 1.0), rot=turn)
        sheet.paste(cell, (10 + i * 74, y0))
    sheet.save(PREVIEW / "shapes.png")


def main():
    MEDIA.mkdir(exist_ok=True)
    imgs = {
        "orb": build((64, 64), orb),
        "sparkle": build((64, 64), sparkle),
        "flash": build((128, 32), flash),
        "flash_v": build((32, 128), flash),  # the flash transposed, for vertical bars
        # orb shapes (see the Shapes section above)
        "retro": retro(),
        "retro_under": retro_under(),
        "retro_twinkle": retro_twinkle(),
        "wisp": build((64, 64), wisp),
        "wisp_under": build((64, 64), wisp_under),
        "power_core": build((64, 64), power_core),
        "bolt1": bolt_ring(301, 2, 1),
        "bolt2": bolt_ring(302, 1, 1),
        "bolt3": bolt_ring(303, 2, 0),
        "bolt4": bolt_ring(304, 3, 0),
    }
    for name, img in imgs.items():
        save_tga(img, MEDIA / f"{name}.tga")
        print(f"wrote media/{name}.tga {img.size}")
    if "--preview" in sys.argv:
        preview(imgs)
        preview_shapes(imgs)
        print(f"wrote {PREVIEW / 'preview.png'} and {PREVIEW / 'shapes.png'}")


if __name__ == "__main__":
    main()
