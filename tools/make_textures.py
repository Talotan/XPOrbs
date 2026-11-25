"""Generate XPOrbs media (white RGBA, tinted in-game with SetVertexColor).

Run: uv run --with pillow python tools/make_textures.py [--preview]
Writes uncompressed 32-bit TGA files with a bottom-left origin to media/.
"""

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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
    return (
        min(1.0, streak_h + streak_v + core * 0.9) * (0.35 + 0.65 * fall)
        if r < 1
        else 0.0
    )


def flash(u, v):
    r = math.hypot(u, v)  # u, v already normalised per axis -> elliptical
    return (1 - r) ** 1.5 if r < 1 else 0.0


def save_tga(img, path):
    # Pillow writes uncompressed 32-bit TGA, bottom-left origin by default (orientation=1).
    img.save(path, format="TGA", compression=None)


# ---------------------------------------------------------------------------
# Orb shapes besides Starlight: Retro (pixel art), Globe (solid ball with a glint), Crackle (core plus bolts).
# Every new texture has power-of-two dimensions (older clients show other sizes as missing); art that is not
# a power of two is padded and the game crops it with SetTexCoord.
# ---------------------------------------------------------------------------


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def globe(u, v):
    """Glowing ball: a hot centred core on a solid plateau, a faint bright rim and a soft halo."""
    r = math.hypot(u, v)
    body = 0.72 * (1 - smoothstep(0.52, 0.74, r))
    core = 0.28 * math.exp(-((r / 0.26) ** 2) / 2)
    rim = 0.10 * math.exp(-(((r - 0.60) / 0.06) ** 2) / 2)
    halo = 0.16 * (1 - smoothstep(0.55, 1.0, r))
    return max(halo, body + core + rim)


def globe_under(u, v):
    """The dark disc under a globe: solid, with a soft edge."""
    return 1 - smoothstep(0.60, 0.82, math.hypot(u, v))


def globe_glint(u, v):
    """A soft highlight: a gaussian blob a little longer along the diagonal that runs up-right (across the line to
    the highlight's up-left position), peak 1.0, faded to nothing well inside the quad. Drawn 0.30 x the globe."""
    along = (u - v) / math.sqrt(
        2
    )  # v grows downwards in the image, so (+u, -v) is up and to the right
    across = (u + v) / math.sqrt(2)
    blob = math.exp(-(along**2 / (2 * 0.52**2) + across**2 / (2 * 0.40**2)))
    return blob * (1 - smoothstep(0.55, 0.95, math.hypot(u, v)))


def crackle_core(u, v):
    """The core of a crackle orb: a hot centre and a fuller halo with a clear edge, so the bolts sit on its rim."""
    r = math.hypot(u, v)
    return min(
        1.0,
        math.exp(-((r / 0.20) ** 2) / 2) + 0.75 * (1 - smoothstep(0.0, 0.70, r)) ** 1.5,
    )


def polar(r, a):
    return (r * math.cos(a), r * math.sin(a))


def bolt_ring(
    seed, n_arcs, spike, size=64, ss=4, width=2.6, glow_sigma=2.0, sharp_sigma=0.45
):
    """A crackling shell: zig-zag arcs of straight segments hugging the core, plus an optional short outward spike.
    Nothing radiates from the centre, so it can't read as legs. Deterministic per seed; stays inside r < 0.92."""
    rnd = random.Random(seed)
    n = size * ss
    core = Image.new("L", (n, n), 0)
    draw = ImageDraw.Draw(core)

    def px(p):
        return ((p[0] + 1) / 2 * n, (p[1] + 1) / 2 * n)

    def stroke(points, w):
        draw.line(
            [px(p) for p in points],
            fill=255,
            width=max(1, round(w * ss)),
            joint="curve",
        )

    base = rnd.uniform(0, 2 * math.pi)
    for k in range(n_arcs):
        a0 = base + 2 * math.pi * k / n_arcs + rnd.uniform(-0.3, 0.3)
        sweep = rnd.uniform(1.2, 2.3)
        segs = rnd.randint(6, 8)
        radius = rnd.uniform(
            0.40, 0.50
        )  # on the rim of crackle_core (the quad is 1.30 x the body)
        sign = rnd.choice([-1, 1])
        points = []
        for i in range(segs + 1):
            a = a0 + sweep * i / segs + rnd.uniform(-0.08, 0.08)
            if (
                rnd.random() < 0.25
            ):  # now and then the zig-zag skips its alternation, so it never reads as a spring
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
        stroke(
            [
                polar(0.32, a),
                polar(0.46, a + 0.25),
                polar(0.51, a - 0.05),
                polar(0.67, a + 0.2),
            ],
            width * 0.8,
        )
    sharp = core.filter(ImageFilter.GaussianBlur(ss * sharp_sigma))
    glow = core.filter(ImageFilter.GaussianBlur(ss * glow_sigma))  # glow gain 1.0
    alpha = ImageChops.lighter(sharp, glow).resize(
        (size, size), Image.Resampling.LANCZOS
    )
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
        img.paste(
            (255, 255, 255, round(a * 255)),
            (c * CELL, r * CELL, (c + 1) * CELL, (r + 1) * CELL),
        )
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


# ---------------------------------------------------------------------------
# Solid variants (the "Solid" blend): the alpha is a hard mask (opaque inside, a ~1.5 px antialiased edge) and the RGB
# carries the shading (1.0 = the full vertex colour, lower = darker), so BLEND reads as a shaded ball, not a flat disc.
# ---------------------------------------------------------------------------


def build_shaded(size, shade_fn, radius, ramp=0.05):
    """RGBA of `size` px: alpha = hard disc of `radius` (in half-widths); RGB = shade_fn(u, v) grey, held at the rim's
    value outside the disc so scaling never bleeds a bright fringe."""
    w, h = size
    img = Image.new("RGBA", size, (255, 255, 255, 0))
    px = img.load()
    for j in range(h):
        for i in range(w):
            u = (i + 0.5) / w * 2 - 1
            v = (j + 0.5) / h * 2 - 1
            r = math.hypot(u, v)
            edge = max(
                0.0, min(1.0, (radius - r) / ramp + 0.5)
            )  # ~1.6 px ramp at 64 px
            if r > radius:
                u, v = u * radius / r, v * radius / r
            g = round(max(0.0, min(1.0, shade_fn(u, v))) * 255)
            px[i, j] = (g, g, g, round(edge * 255))
    return img


GLOBE_SOLID_R = 0.72  # the globe body's plateau radius
CRACKLE_SOLID_R = 0.40  # smaller than the core's visible edge (~0.5), which restores the dark gap before the bolts
_LIGHT = (-0.5, 0.5, 0.7)  # towards the light: up, left, front
_LIGHT_LEN = math.sqrt(sum(c * c for c in _LIGHT))


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
                    px_b[x, y] = (
                        min(255, int(br + r * k)),
                        min(255, int(bg_ + g * k)),
                        min(255, int(bb + b * k)),
                        255,
                    )

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
                    px_b[x, y] = (
                        int(br * (1 - k) + r * k),
                        int(bg_ * (1 - k) + g * k),
                        int(bb * (1 - k) + b * k),
                        255,
                    )

    blue, purple = (51, 128, 255), (255, 77, 217)
    under = (5, 20, 77)
    glow, size = (
        2.0,
        14,
    )  # in-game: orb drawn at size * GLOW, underlay at 1.25x that, sparkle at size * 1.9

    def lighten(rgb):
        return tuple(int(c + (255 - c) * 0.25) for c in rgb)

    def curve(
        t,
    ):  # stand-in for the pop-then-home path: up and out, then home to the bar
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
            gx, gy = curve(
                max(0.0, t - 0.015 * g * 6)
            )  # exaggerated step so the ghosts show at this scale
            gsz = int(sz * glow * gs)
            if g == 0:
                usz = int(sz * glow * 1.25)
                blend(
                    bg,
                    tint(imgs["orb"], under),
                    (int(gx) - usz // 2, int(gy) - usz // 2),
                    (usz, usz),
                    0.45,
                )
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

SIZES = {
    "Starlight": 14,
    "Retro": 2,
    "Globe": 14,
    "Crackle": 14,
}  # the per-shape default db.size (Retro: px per cell)
RETRO_K = 24 / 14  # Shapes.lua / Core.lua: size units to px for Retro
SOLID_LIFT = 0.06  # Solid shows the raw vertex colour (ADD brightens), so its colour is lightened by this much


def orb_size(kind):
    """ns.OrbSize: the size in the units Starlight's db.size uses (Retro stores px per cell, 8 cells across)."""
    return SIZES[kind] * 8 / RETRO_K if kind == "Retro" else SIZES[kind]


def retro_cell():
    """Shapes.lua retroCell at burst scale 1: the stored step, via the OrbSize round trip."""
    return max(1, math.floor(orb_size("Retro") * RETRO_K / 8 + 0.5))


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
    SIZE = SIZES[kind]
    if kind == "Starlight":
        body = SIZE * 2.0
        if trail:
            for gap, a, s in ((24, 0.30, 0.70), (12, 0.55, 0.85)):
                add_layer(
                    canvas, tex["orb"], col, x - ux * gap, y - uy * gap, body * s, a
                )
        blend_layer(canvas, tex["orb"], dim, x, y, body * 1.25, 0.45)
        add_layer(canvas, tex["orb"], col, x, y, body)
        add_layer(
            canvas,
            tex["sparkle"],
            lighten(col, 0.15),
            x,
            y,
            SIZE * 1.9,
            0.6,
            rot=math.degrees(t * 2 * math.pi),
        )
    elif kind == "Retro":
        cell = retro_cell()  # one cell size for the whole burst

        def snap(v):
            return math.floor(v / cell + 0.5) * cell

        gx, gy = snap(x), snap(y)
        if (
            trail
        ):  # two plain squares: 2 x 2 cells 6 cells behind, 1 cell 10 cells behind
            add_square(
                canvas,
                col,
                snap(x - ux * 6 * cell),
                snap(y - uy * 6 * cell),
                2 * cell,
                0.70,
            )
            sx = (math.floor((x - ux * 10 * cell) / cell) + 0.5) * cell
            sy = (math.floor((y - uy * 10 * cell) / cell) + 0.5) * cell
            add_square(canvas, col, sx, sy, cell, 0.40)
        under = tex["retro_under"].crop((0, 0, 80, 80))
        blend_layer(canvas, under, dim, gx, gy, 10 * cell, 0.9, True)
        add_layer(canvas, tex["retro"], col, gx, gy, 8 * cell, 1.0, True)
        if (t + 0.1) % 0.5 < 0.25:  # the twinkle blinks 0.25 s on, 0.25 s off
            twinkle = tex["retro_twinkle"].crop((0, 0, 24, 24))
            add_layer(
                canvas,
                twinkle,
                lighten(col, 0.5),
                gx - 2.5 * cell,
                gy - 2.5 * cell,
                3 * cell,
                1.0,
                True,
            )
    elif kind == "Globe":
        body = SIZE * 1.5 * (1 + 0.06 * math.sin(2 * math.pi * 2.5 * t))
        if trail:
            for gap, a, s in (
                (40, 0.12, 0.55),
                (30, 0.22, 0.65),
                (20, 0.36, 0.75),
                (10, 0.52, 0.87),
            ):
                add_layer(
                    canvas, tex["globe"], col, x - ux * gap, y - uy * gap, body * s, a
                )
        blend_layer(canvas, tex["globe_under"], dim, x, y, body, 0.80)
        add_layer(canvas, tex["globe"], col, x, y, body)
        # the glint: 0.30 x the body, up and to the left (the canvas y grows downwards), ADD, 0.55, white 0.75
        add_layer(
            canvas,
            tex["globe_glint"],
            lighten(col, 0.75),
            x - 0.20 * body,
            y - 0.20 * body,
            body * 0.30,
            0.55,
        )
    else:  # Crackle
        body = SIZE * 2.0
        if trail:
            for gap, a, s in ((20, 0.30, 0.70), (10, 0.55, 0.85)):
                add_layer(
                    canvas,
                    tex["crackle_core"],
                    col,
                    x - ux * gap,
                    y - uy * gap,
                    body * s,
                    a,
                )
        blend_layer(canvas, tex["orb"], dim, x, y, body * 1.6, 0.58)
        add_layer(canvas, tex["crackle_core"], col, x, y, body * 1.15)
        bolt = tex[f"bolt{rnd.randint(1, 4)}"]
        add_layer(
            canvas,
            bolt,
            lighten(col, 0.15),
            x,
            y,
            body * 1.30,
            rnd.uniform(0.7, 1.0),
            rot=rnd.uniform(0, 360),
        )


def _background(kind, w, h, seed):
    if kind == "dark":
        return Image.new("RGB", (w, h), (14, 18, 30))
    noise = Image.effect_noise((w, h), 40).convert("RGB")  # mid-grey noise: lumpy grass
    return Image.blend(Image.new("RGB", (w, h), (104, 148, 66)), noise, 0.12)


def preview_shapes(imgs):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    tex = _alphas(imgs)
    kinds = ["Starlight", "Retro", "Globe", "Crackle"]
    pw, ph = 380, 150
    sheet = Image.new("RGB", (2 * pw + 30, 4 * (ph + 22) + 20 + 150), (30, 30, 36))
    draw = ImageDraw.Draw(sheet)
    for row, kind in enumerate(kinds):
        for col_i, bg_kind in enumerate(["dark", "grass"]):
            rnd = random.Random(row * 2 + col_i)
            panel = _background(bg_kind, pw, ph, row)
            for i in range(
                12
            ):  # 12 orbs, every one heading somewhere between right and up-right
                ang = rnd.uniform(-0.6, 0.6)
                ux, uy = math.cos(ang), -math.sin(ang)
                x, y = (
                    40 + (i % 6) * 58 + rnd.uniform(-8, 8),
                    38 + (i // 6) * 70 + rnd.uniform(-10, 10),
                )
                col = PURPLE if i % 4 == 0 else BLUE
                draw_orb(panel, kind, tex, col, x, y, ux, uy, rnd.uniform(0, 2), rnd)
            x0, y0 = 10 + col_i * (pw + 10), 10 + row * (ph + 22) + 16
            sheet.paste(panel, (x0, y0))
            label = f"{kind} (size {SIZES[kind]}) / {bg_kind}"
            draw.text((x0, y0 - 14), label, fill=(210, 210, 215))
    # ten consecutive ticks of one Crackle orb (a tick is 70-90 ms): the bolt changes frame, angle and brightness
    y0 = 10 + 4 * (ph + 22) + 16
    draw.text((10, y0 - 14), "Crackle: ten bolt ticks", fill=(210, 210, 215))
    rnd = random.Random(99)
    frame, turn = 1, 0.0
    for i in range(10):
        cell = _background("dark", 70, 110, 0)
        frame = (
            frame + rnd.randint(0, 2)
        ) % 4 + 1  # never the same frame twice running
        turn += rnd.uniform(60, 300)
        bolt = tex[f"bolt{frame}"]
        body = SIZES["Crackle"] * 2.0
        blend_layer(
            cell, tex["orb"], tuple(c * 0.25 for c in BLUE), 35, 55, body * 1.6, 0.58
        )
        add_layer(cell, tex["crackle_core"], BLUE, 35, 55, body * 1.15)
        add_layer(
            cell,
            bolt,
            lighten(BLUE, 0.15),
            35,
            55,
            body * 1.30,
            rnd.uniform(0.7, 1.0),
            rot=turn,
        )
        sheet.paste(cell, (10 + i * 74, y0))
    sheet.save(PREVIEW / "shapes.png")


# --- blend sheet: Natural (additive) against Solid (opaque, layered) -----------------------------------------------------

# Constants to reuse when Solid is wired into Shapes.lua. Crackle's underlay is lighter in Solid, so the bolts still read.
CRACKLE_SOLID_UNDER, CRACKLE_SOLID_UNDER_ALPHA = (
    1.25,
    0.40,
)  # x body, alpha (Natural: 1.6 x body, 0.58)
# Solid draw order (sublayers): all underlays, then all trails, then bodies, then the top layer (glint, bolts, twinkle).
SOLID_SUBLAYERS = {"under": -2, "trail": -1, "body": 0, "top": 1}
NATURAL_SUBLAYERS = {"under": -1, "trail": 0, "body": 0, "top": 1}


def blend_tex(canvas, img, col, cx, cy, size, amul=1.0, nearest=False):
    """BLEND with a texture whose RGB matters: dst = lerp(dst, tex.rgb * colour, tex.a * amul)."""
    size = max(1, round(size))
    resample = Image.Resampling.NEAREST if nearest else Image.Resampling.LANCZOS
    t = img.resize((size, size), resample)
    a = t.getchannel("A").point(lambda p: int(p * amul))
    tint = Image.merge(
        "RGB",
        [
            ch.point(lambda p, c=c: int(p * c))
            for ch, c in zip(t.convert("RGB").split(), col)
        ],
    )
    box = _box(cx, cy, size)
    canvas.paste(Image.composite(tint, canvas.crop(box), a), box[:2])


def orb_ops(
    kind, mode, imgs, col, x, y, ux, uy, t, rnd, trail=True, solid_trail=False, opt=None
):
    """The draw calls of one orb as [(sublayer, fn(canvas))]; sorted (stable) by sublayer across a whole panel.
    Natural keeps today's order; Solid draws underlays, trails, bodies, then the top layer. solid_trail: Solid's
    trails are opaque (BLEND, lifted colour, same alpha ladder) instead of glowing (ADD). opt (Solid only, dev sheet):
    lift, under (x the underlay alpha), extra (x the additive glint / bolts / twinkle alpha)."""
    opt = opt or {}
    under_k, extra_k = opt.get("under", 1.0), opt.get("extra", 1.0)
    tex = _alphas(imgs)
    solid = mode == "solid"
    sl = SOLID_SUBLAYERS if solid else NATURAL_SUBLAYERS
    body_col = lighten(col, opt.get("lift", SOLID_LIFT)) if solid else col
    dim = tuple(c * 0.25 for c in col)
    ops = []
    SIZE = SIZES[kind]

    def ghost(name, solid_name, gap, a, s, body):
        gx, gy = x - ux * gap, y - uy * gap
        if solid and solid_trail and solid_name:
            ops.append(
                (
                    sl["trail"],
                    lambda c: blend_tex(
                        c, imgs[solid_name], body_col, gx, gy, body * s, a
                    ),
                )
            )
        else:
            ops.append(
                (
                    sl["trail"],
                    lambda c: add_layer(c, tex[name], col, gx, gy, body * s, a),
                )
            )

    if kind == "Starlight":
        body = SIZE * 2.0
        if trail:
            for gap, a, s in ((24, 0.30, 0.70), (12, 0.55, 0.85)):
                ghost("orb", "globe_solid", gap, a, s, body)
        ops.append(
            (
                sl["under"],
                lambda c: blend_layer(c, tex["orb"], dim, x, y, body * 1.25, 0.45),
            )
        )
        if solid:  # mock, never shipped: globe_solid scaled to Starlight's body
            ops.append(
                (
                    sl["body"],
                    lambda c: blend_tex(c, imgs["globe_solid"], body_col, x, y, body),
                )
            )
        else:
            ops.append(
                (sl["body"], lambda c: add_layer(c, tex["orb"], col, x, y, body))
            )
        ops.append(
            (
                sl["top"],
                lambda c: add_layer(
                    c,
                    tex["sparkle"],
                    lighten(col, 0.15),
                    x,
                    y,
                    SIZE * 1.9,
                    0.6,
                    rot=math.degrees(t * 2 * math.pi),
                ),
            )
        )
    elif kind == "Retro":
        cell = retro_cell()

        def snap(v):
            return math.floor(v / cell + 0.5) * cell

        gx, gy = snap(x), snap(y)
        if trail:  # plain colour squares: always glowing
            ops.append(
                (
                    sl["trail"],
                    lambda c: add_square(
                        c,
                        col,
                        snap(x - ux * 6 * cell),
                        snap(y - uy * 6 * cell),
                        2 * cell,
                        0.70,
                    ),
                )
            )
            sx = (math.floor((x - ux * 10 * cell) / cell) + 0.5) * cell
            sy = (math.floor((y - uy * 10 * cell) / cell) + 0.5) * cell
            ops.append((sl["trail"], lambda c: add_square(c, col, sx, sy, cell, 0.40)))
        under = tex["retro_under"].crop((0, 0, 80, 80))
        ops.append(
            (
                sl["under"],
                lambda c: blend_layer(
                    c, under, dim, gx, gy, 10 * cell, min(1.0, 0.9 * under_k), True
                ),
            )
        )
        if solid:
            ops.append(
                (
                    sl["body"],
                    lambda c: blend_tex(
                        c, imgs["retro_solid"], body_col, gx, gy, 8 * cell, nearest=True
                    ),
                )
            )
        else:
            ops.append(
                (
                    sl["body"],
                    lambda c: add_layer(
                        c, tex["retro"], col, gx, gy, 8 * cell, 1.0, True
                    ),
                )
            )
        if (t + 0.1) % 0.5 < 0.25:
            twinkle = tex["retro_twinkle"].crop((0, 0, 24, 24))
            ops.append(
                (
                    sl["top"],
                    lambda c: add_layer(
                        c,
                        twinkle,
                        lighten(col, 0.5),
                        gx - 2.5 * cell,
                        gy - 2.5 * cell,
                        3 * cell,
                        min(1.0, extra_k),
                        True,
                    ),
                )
            )
    elif kind == "Globe":
        body = SIZE * 1.5 * (1 + 0.06 * math.sin(2 * math.pi * 2.5 * t))
        if trail:
            for gap, a, s in (
                (40, 0.12, 0.55),
                (30, 0.22, 0.65),
                (20, 0.36, 0.75),
                (10, 0.52, 0.87),
            ):
                ghost("globe", "globe_solid", gap, a, s, body)
        ops.append(
            (
                sl["under"],
                lambda c: blend_layer(
                    c, tex["globe_under"], dim, x, y, body, min(1.0, 0.80 * under_k)
                ),
            )
        )
        if solid:
            ops.append(
                (
                    sl["body"],
                    lambda c: blend_tex(c, imgs["globe_solid"], body_col, x, y, body),
                )
            )
        else:
            ops.append(
                (sl["body"], lambda c: add_layer(c, tex["globe"], col, x, y, body))
            )
        ops.append(
            (
                sl["top"],
                lambda c: add_layer(
                    c,
                    tex["globe_glint"],
                    lighten(col, 0.75),
                    x - 0.20 * body,
                    y - 0.20 * body,
                    body * 0.30,
                    min(1.0, 0.55 * extra_k),
                ),
            )
        )
    else:  # Crackle
        body = SIZE * 2.0
        if trail:
            for gap, a, s in ((20, 0.30, 0.70), (10, 0.55, 0.85)):
                ghost("crackle_core", "crackle_core_solid", gap, a, s, body)
        if solid:
            ops.append(
                (
                    sl["under"],
                    lambda c: blend_layer(
                        c,
                        tex["orb"],
                        dim,
                        x,
                        y,
                        body * CRACKLE_SOLID_UNDER,
                        min(1.0, CRACKLE_SOLID_UNDER_ALPHA * under_k),
                    ),
                )
            )
            ops.append(
                (
                    sl["body"],
                    lambda c: blend_tex(
                        c, imgs["crackle_core_solid"], body_col, x, y, body * 1.15
                    ),
                )
            )
        else:
            ops.append(
                (
                    sl["under"],
                    lambda c: blend_layer(c, tex["orb"], dim, x, y, body * 1.6, 0.58),
                )
            )
            ops.append(
                (
                    sl["body"],
                    lambda c: add_layer(c, tex["crackle_core"], col, x, y, body * 1.15),
                )
            )
        bolt, bolt_a, bolt_rot = (
            tex[f"bolt{rnd.randint(1, 4)}"],
            rnd.uniform(0.7, 1.0),
            rnd.uniform(0, 360),
        )
        ops.append(
            (
                sl["top"],
                lambda c: add_layer(
                    c,
                    bolt,
                    lighten(col, 0.15),
                    x,
                    y,
                    body * 1.30,
                    min(1.0, bolt_a * extra_k),
                    rot=bolt_rot,
                ),
            )
        )
    return ops


def visible_d(kind):
    """The visible disc diameter in drawn px (not the quad), for spacing the overlapping pile."""
    if kind == "Retro":
        return 8 * retro_cell()
    if kind == "Globe":
        return GLOBE_SOLID_R * SIZES["Globe"] * 1.5
    if kind == "Crackle":
        return 2 * CRACKLE_SOLID_R * SIZES["Crackle"] * 2.0 * 1.15
    return GLOBE_SOLID_R * SIZES["Starlight"] * 2.0  # the Starlight solid mock


# a loose pile: 4 purple + 1 blue, offsets in units of ~0.58 x the visible diameter
PILE = ((-1.0, 0.3, 0), (-0.2, -0.4, 0), (0.4, 0.5, 0), (1.0, -0.2, 1), (0.0, 0.25, 0))


def sheet_ground(ground, w, h):
    if ground == "sand":
        noise = Image.effect_noise((w, h), 40).convert("RGB")
        return Image.blend(Image.new("RGB", (w, h), (196, 178, 136)), noise, 0.12)
    return _background(ground, w, h, 0)


def pile_panel(
    kind, mode, imgs, ground, w, h, cx, cy, stream=False, solid_trail=False, opt=None
):
    """One panel: the pile centred at (cx, cy) and, if stream, a 3-orb stream (trails on) to its right."""
    panel = sheet_ground(ground, w, h)
    rnd = random.Random(7)
    d = 0.58 * visible_d(kind)
    ops = []
    for dx, dy, blue in PILE:
        col = BLUE if blue else PURPLE
        ops += orb_ops(
            kind,
            mode,
            imgs,
            col,
            cx + dx * d,
            cy + dy * d,
            1.0,
            0.0,
            rnd.uniform(0, 2),
            rnd,
            trail=False,
            opt=opt,
        )
    if stream:
        ux, uy = math.cos(0.12), -math.sin(0.12)
        for i in range(3):
            x = cx + 62 + i * (0.9 * visible_d(kind) + 20)
            ops += orb_ops(
                kind,
                mode,
                imgs,
                PURPLE,
                x,
                cy + 6 - i * 4,
                ux,
                uy,
                rnd.uniform(0, 2),
                rnd,
                trail=True,
                solid_trail=solid_trail,
                opt=opt,
            )
    for _, fn in sorted(ops, key=lambda o: o[0]):
        fn(panel)
    return panel


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an old Pillow
        return ImageFont.load_default()


def preview_blend(imgs):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    font, small = _font(14), _font(12)
    grounds = ["dark", "grass", "sand"]
    sw, sh, zw, zh, Z = 240, 84, 80, 60, 3  # strip panel, zoom source, zoom factor
    gut, left = 6, 110
    colw = max(sw, zw * Z)
    W = left + 6 * (colw + gut) + 10
    ink, dim = (240, 240, 244), (170, 170, 180)

    # (row label, kind, solid_trail?, show the Natural column?)
    strip_rows = [
        ("Retro", "Retro", False, True),
        ("Globe", "Globe", False, True),
        ("Globe\nsolid trail", "Globe", True, False),
        ("Crackle", "Crackle", False, True),
        ("Crackle\nsolid trail", "Crackle", True, False),
    ]
    zoom_rows = [("Retro", "Retro"), ("Globe", "Globe"), ("Crackle", "Crackle")]
    mock_rows = [("Starlight\nsolid mock", "Starlight")]
    head, block_h = 48, 26
    H = (
        46
        + head
        + len(strip_rows) * (sh + gut)
        + block_h
        + head
        + len(zoom_rows) * (zh * Z + gut)
        + 40
        + block_h
        + head
        + (sh + gut)
        + (zh * Z + gut)
        + 50
    )
    sheet = Image.new("RGB", (W, H), (30, 30, 36))
    dr = ImageDraw.Draw(sheet)

    def col_x(ground_i, mode_i):
        return left + (ground_i * 2 + mode_i) * (colw + gut)

    def headers(y):
        for gi, g in enumerate(grounds):
            dr.text((col_x(gi, 0), y), g, fill=ink, font=font)
            dr.text((col_x(gi, 0), y + 18), "Natural", fill=dim, font=small)
            dr.text((col_x(gi, 1), y + 18), "Solid", fill=dim, font=small)

    def row_label(y, text, hh):
        for i, line in enumerate(text.split("\n")):
            dr.text(
                (10, y + hh // 2 - 8 + i * 15 - (7 if "\n" in text else 0)),
                line,
                fill=ink if i == 0 else dim,
                font=font if i == 0 else small,
            )

    def strips(y, rows):
        for label, kind, solid_trail, natural in rows:
            row_label(y, label, sh)
            for gi, g in enumerate(grounds):
                if natural:
                    sheet.paste(
                        pile_panel(
                            kind, "natural", imgs, g, sw, sh, 48, sh // 2, stream=True
                        ),
                        (col_x(gi, 0), y),
                    )
                sheet.paste(
                    pile_panel(
                        kind,
                        "solid",
                        imgs,
                        g,
                        sw,
                        sh,
                        48,
                        sh // 2,
                        stream=True,
                        solid_trail=solid_trail,
                    ),
                    (col_x(gi, 1), y),
                )
            y += sh + gut
        return y

    def zooms(y, rows):
        for label, kind in rows:
            row_label(y, label, zh * Z)
            for gi, g in enumerate(grounds):
                for mi, mode in enumerate(("natural", "solid")):
                    p = pile_panel(kind, mode, imgs, g, zw, zh, zw // 2, zh // 2)
                    sheet.paste(
                        p.resize((zw * Z, zh * Z), Image.Resampling.NEAREST),
                        (col_x(gi, mi), y),
                    )
            y += zh * Z + gut
        return y

    dr.text(
        (10, 10),
        f"Natural vs Solid - SOLID_LIFT = {SOLID_LIFT}",
        fill=ink,
        font=_font(18),
    )
    y = 46
    dr.text((10, y - 4), "1x", fill=dim, font=small)
    y += 6
    headers(y)
    y = strips(y + head, strip_rows)
    y += block_h
    dr.text((10, y), "3x zoom", fill=dim, font=small)
    headers(y)
    y = zooms(y + head, zoom_rows)
    y += 20
    dr.line([(10, y), (W - 10, y)], fill=(120, 120, 130), width=1)
    dr.text(
        (10, y + 4),
        "Not shipping: Starlight keeps its glow. This is only to compare Solid on the old orb.",
        fill=ink,
        font=font,
    )
    y += block_h
    headers(y)
    y = strips(y + head, [(l, k, False, True) for l, k in mock_rows])
    y = zooms(y, mock_rows)
    dr.text(
        (10, H - 24),
        "Draw order, Natural: as today. Solid: all underlays, then all trails, then all bodies, then "
        'glint / bolts / twinkle (additive). Solid trails stay additive.',
        fill=dim,
        font=small,
    )
    sheet.save(PREVIEW / "blend.png")


# --- Solid look variants (dev comparison sheet; nothing here writes media/) --------------------------------------------
# One parameterised shading family per shape. Variant "B" is the shipped bake (these tables ARE the Solid textures and
# the sheet asserts it); "A" is the old baseline kept for reference. To adopt another variant, point _default_solid at
# it and copy its lift (SOLID_LIFT here and in Shapes.lua) and underlay/extra alphas.
# Per-variant "opt" feeds orb_ops: lift, under (x underlay alpha), extra (x additive glint / bolts / twinkle alpha).

GLOBE_VARIANTS = {
    "A": dict(name="old", base=0.50, gain=0.65, wrap=0.0, rim=0.07, rim_shade=0.6, ramp=0.05,
              lift=0.06, under=1.0, extra=1.0),
    "B": dict(name="softer terminator (DEFAULT)", base=0.70, gain=0.30, wrap=0.6, rim=0.07, rim_shade=0.6, ramp=0.05,
              lift=0.06, under=1.0, extra=1.0),
    "C": dict(name="no baked rim", base=0.50, gain=0.65, wrap=0.0, rim=0.0, rim_shade=1.0, ramp=0.09,
              lift=0.06, under=1.0, extra=1.0),
    "D": dict(name="inner glow", radial=(1.0, 0.38, 2.2), rim=0.0, rim_shade=1.0, ramp=0.07,
              lift=0.14, under=1.0, extra=1.0),
    "E": dict(name="flat + soft edge", base=0.92, gain=0.08, wrap=0.0, rim=0.0, rim_shade=1.0, ramp=0.26, radius=0.78,
              lift=0.06, under=0.8, extra=1.5),
    "F": dict(name="higher lift, gentle", base=0.80, gain=0.20, wrap=0.3, rim=0.07, rim_shade=0.85, ramp=0.05,
              lift=0.18, under=1.0, extra=1.0),
}  # fmt: skip
CRACKLE_VARIANTS = {
    "A": dict(name="old", fall=0.30, power=2.0, rim=0.07, rim_shade=0.6, ramp=0.05,
              lift=0.06, under=1.0, extra=1.0),
    "B": dict(name="softer falloff (DEFAULT)", fall=0.15, power=2.0, rim=0.07, rim_shade=0.8, ramp=0.05,
              lift=0.06, under=1.0, extra=1.0),
    "C": dict(name="no baked rim", fall=0.30, power=2.0, rim=0.0, rim_shade=1.0, ramp=0.09,
              lift=0.06, under=1.0, extra=1.0),
    "D": dict(name="inner glow", fall=0.50, power=2.6, rim=0.0, rim_shade=1.0, ramp=0.07,
              lift=0.20, under=1.0, extra=1.0),
    "E": dict(name="flat + soft edge", fall=0.05, power=2.0, rim=0.0, rim_shade=1.0, ramp=0.22, radius=0.48,
              lift=0.06, under=0.8, extra=1.3),
    "F": dict(name="higher lift, gentle", fall=0.20, power=2.0, rim=0.07, rim_shade=0.85, ramp=0.05,
              lift=0.18, under=1.0, extra=1.0),
}  # fmt: skip
# Retro: levels = (core 4x4, ring, outer); core2 = optional brighter 2x2 core inside the 4x4; drop_outer removes the
# outer cells (the underlay alone outlines it). The two shine cells are always 1.0.
RETRO_VARIANTS = {
    "A": dict(name="old", levels=(1.00, 0.78, 0.50), core2=None, drop_outer=False,
              lift=0.06, under=1.0, extra=1.0),
    "B": dict(name="softer steps (DEFAULT)", levels=(1.00, 0.88, 0.72), core2=None, drop_outer=False,
              lift=0.06, under=1.0, extra=1.0),
    "C": dict(name="no outer level", levels=(1.00, 0.78, 0.78), core2=None, drop_outer=True,
              lift=0.06, under=1.0, extra=1.0),
    "D": dict(name="inner glow", levels=(0.94, 0.80, 0.64), core2=1.00, drop_outer=False,
              lift=0.18, under=1.0, extra=1.0),
    "E": dict(name="two levels", levels=(1.00, 0.90, 0.90), core2=None, drop_outer=False,
              lift=0.06, under=0.8, extra=1.3),
    "F": dict(name="higher lift, gentle", levels=(1.00, 0.90, 0.80), core2=None, drop_outer=False,
              lift=0.18, under=1.0, extra=1.0),
}  # fmt: skip


def _rim(r, R, p, shade):
    return shade * p["rim_shade"] if p["rim"] and r > R - p["rim"] else shade


def globe_variant_shade(p):
    R = p.get("radius", GLOBE_SOLID_R)

    def fn(u, v):
        r = math.hypot(u, v)
        if "radial" in p:  # inner glow: brightest at the centre, smooth falloff to a coloured edge
            top, drop, power = p["radial"]
            return _rim(r, R, p, top - drop * min(1.0, r / R) ** power)
        x, y = u / R, -v / R
        z = math.sqrt(max(0.0, 1 - x * x - y * y))
        d = (x * _LIGHT[0] + y * _LIGHT[1] + z * _LIGHT[2]) / _LIGHT_LEN
        lam = max(0.0, min(1.0, (d + p["wrap"]) / (1 + p["wrap"])))
        return _rim(r, R, p, min(1.0, p["base"] + p["gain"] * lam))

    return fn, R


def crackle_variant_shade(p):
    R = p.get("radius", CRACKLE_SOLID_R)

    def fn(u, v):
        r = math.hypot(u, v)
        return _rim(r, R, p, 1.0 - p["fall"] * min(1.0, r / R) ** p["power"])

    return fn, R


def retro_variant(p):
    core, ring, outer = p["levels"]
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for c, r in OCTAGON:
        dx, dy = c - 3.5, r - 3.5
        box = max(abs(dx), abs(dy))
        if box <= 1.5:
            lv = p["core2"] if (p["core2"] and box <= 0.5) else core
        elif math.hypot(dx, dy) < 3.2:
            lv = ring
        elif p["drop_outer"]:
            continue
        else:
            lv = outer
        if (c, r) in ((2, 2), (3, 2)):
            lv = 1.0  # shine
        g = round(lv * 255)
        img.paste((g, g, g, 255), (c * CELL, r * CELL, (c + 1) * CELL, (r + 1) * CELL))
    return img


def variant_imgs(kind, p, imgs):
    out = dict(imgs)
    if kind == "Retro":
        out["retro_solid"] = retro_variant(p)
    elif kind == "Globe":
        fn, R = globe_variant_shade(p)
        out["globe_solid"] = build_shaded((64, 64), fn, R, p["ramp"])
    else:
        fn, R = crackle_variant_shade(p)
        out["crackle_core_solid"] = build_shaded((64, 64), fn, R, p["ramp"])
    return out


def _params_line(kind, p):
    if kind == "Retro":
        c, r, o = p["levels"]
        lv = f"{c:.2f}/{r:.2f}/{'-' if p['drop_outer'] else format(o, '.2f')}"
        if p["core2"]:
            lv = f"2x2 {p['core2']:.2f}, " + lv
        s = f"levels {lv}"
    elif kind == "Globe":
        if "radial" in p:
            t, d, e = p["radial"]
            s = f"radial {t:.2f} - {d:.2f}*r^{e:g}"
        else:
            s = f"{p['base']:.2f} + {p['gain']:.2f}*lambert (wrap {p['wrap']:g})"
    else:
        s = f"1 - {p['fall']:.2f}*r^{p['power']:g}"
    if kind != "Retro":
        s += f", rim {format(p['rim_shade'], 'g') if p['rim'] else 'none'}, edge ramp {p['ramp']:g}"
        if "radius" in p:
            s += f", R {p['radius']:g}"
    return f"{s} | lift {p['lift']:g}, underlay x{p['under']:g}, extra x{p['extra']:g}"


def _render_rows(kind, title, rows, path):
    """rows = (label, params line, mode, imgs, opt); columns dark / grass / sand, each a 1x pile + 3x nearest zoom."""
    grounds = ["dark", "grass", "sand"]
    pw, ph, Z, gut, left = 90, 62, 3, 8, 330
    colw = pw + gut + pw * Z
    W = left + 3 * (colw + 14) + 10
    head, rowh = 64, ph * Z + gut
    ink, dim, accent = (240, 240, 244), (165, 165, 178), (255, 214, 120)
    big, font, small = _font(26), _font(15), _font(13)
    sheet = Image.new("RGB", (W, head + len(rows) * rowh + 16), (30, 30, 36))
    dr = ImageDraw.Draw(sheet)
    dr.text((10, 8), title, fill=ink, font=_font(22))
    dr.text((330, 14), "5-orb pile (4 purple + 1 rested blue), 1x then 3x nearest; glint/bolts/twinkle as in game",
            fill=dim, font=small)
    for gi, g in enumerate(grounds):
        dr.text((left + gi * (colw + 14), 42), g, fill=ink, font=font)
    y = head
    for label, params, mode, im, p in rows:
        dr.text((10, y + 6), label, fill=accent if mode == "solid" else ink, font=big)
        line, ly = "", y + 44
        for word in params.split(" "):
            if len(line) + len(word) > 38:
                dr.text((10, ly), line, fill=dim, font=small)
                line, ly = "", ly + 16
            line += word + " "
        dr.text((10, ly), line, fill=dim, font=small)
        for gi, g in enumerate(grounds):
            panel = pile_panel(kind, mode, im, g, pw, ph, pw // 2, ph // 2, opt=p)
            x0 = left + gi * (colw + 14)
            sheet.paste(panel, (x0, y))
            sheet.paste(panel.resize((pw * Z, ph * Z), Image.Resampling.NEAREST), (x0 + pw + gut, y))
        y += rowh
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    print(f"wrote {path} {sheet.size}")


def solid_variants_sheet(imgs, out):
    """Per shape: a Natural reference row then A-F (B = the shipped default)."""
    tables = {"Retro": RETRO_VARIANTS, "Globe": GLOBE_VARIANTS, "Crackle": CRACKLE_VARIANTS}
    for kind, key in (("Retro", "retro_solid"), ("Globe", "globe_solid"), ("Crackle", "crackle_core_solid")):
        b = variant_imgs(kind, tables[kind]["B"], imgs)[key]  # variant B must equal the shipped bake
        assert b.tobytes() == imgs[key].tobytes(), f"{kind} variant B differs from the shipped Solid bake"
    out = Path(out)
    for kind, table in tables.items():
        rows = [("Natural (Glow)", "reference: the additive look", "natural", imgs, None)]
        for letter, p in table.items():
            rows.append((f"{letter}  {p['name']}", _params_line(kind, p), "solid", variant_imgs(kind, p, imgs), p))
        path = out.with_name(f"{out.stem}-{kind.lower()}{out.suffix or '.png'}")
        _render_rows(kind, f"{kind} - Solid variants", rows, path)


def globe_rim_compare(imgs, out):
    """Globe Solid B with the wired rim (0.6) against B with a milder rim (0.8), with Glow and the old A for reference."""
    G = GLOBE_VARIANTS
    rows = [
        ("Natural (Glow)", "reference", "natural", imgs, None),
        ("A  old", _params_line("Globe", G["A"]), "solid", variant_imgs("Globe", G["A"], imgs), G["A"]),
        ("B  rim 0.6 (wired)", _params_line("Globe", G["B"]), "solid", variant_imgs("Globe", G["B"], imgs), G["B"]),
    ]
    p8 = dict(G["B"], rim_shade=0.8)
    rows.append(("B  rim 0.8", _params_line("Globe", p8), "solid", variant_imgs("Globe", p8, imgs), p8))
    _render_rows("Globe", "Globe Solid B: rim 0.6 vs 0.8", rows, Path(out))


def _default_solid(kind, key):
    """The shipped Solid texture: variant B of the tables above."""
    table = {"Retro": RETRO_VARIANTS, "Globe": GLOBE_VARIANTS, "Crackle": CRACKLE_VARIANTS}[kind]
    return variant_imgs(kind, table["B"], {})[key]


def build_imgs():
    return {
        "orb": build((64, 64), orb),
        "sparkle": build((64, 64), sparkle),
        "flash": build((128, 32), flash),
        "flash_v": build((32, 128), flash),  # the flash transposed, for vertical bars
        # orb shapes (see the Shapes section above)
        "retro": retro(),
        "retro_under": retro_under(),
        "retro_twinkle": retro_twinkle(),
        "globe": build((64, 64), globe),
        "globe_under": build((64, 64), globe_under),
        "globe_glint": build((64, 64), globe_glint),
        "crackle_core": build((64, 64), crackle_core),
        # Solid blend variants (hard alpha mask, RGB shading)
        "globe_solid": _default_solid("Globe", "globe_solid"),
        "crackle_core_solid": _default_solid("Crackle", "crackle_core_solid"),
        "retro_solid": _default_solid("Retro", "retro_solid"),
        "bolt1": bolt_ring(301, 2, 1),
        "bolt2": bolt_ring(302, 1, 1),
        "bolt3": bolt_ring(303, 2, 0),
        "bolt4": bolt_ring(309, 3, 0),
    }


def main():
    if "--solid-variants" in sys.argv:  # dev sheet only: builds in memory, never writes media/
        i = sys.argv.index("--solid-variants")
        if i + 1 >= len(sys.argv):
            sys.exit("usage: make_textures.py --solid-variants <out.png>")
        solid_variants_sheet(build_imgs(), Path(sys.argv[i + 1]))
        return
    if "--globe-rim-compare" in sys.argv:
        i = sys.argv.index("--globe-rim-compare")
        globe_rim_compare(build_imgs(), Path(sys.argv[i + 1]))
        return
    MEDIA.mkdir(exist_ok=True)
    imgs = build_imgs()
    for name, img in imgs.items():
        save_tga(img, MEDIA / f"{name}.tga")
        print(f"wrote media/{name}.tga {img.size}")
    if "--preview" in sys.argv:
        preview(imgs)
        preview_shapes(imgs)
        preview_blend(imgs)
        print(
            f"wrote {PREVIEW / 'preview.png'}, {PREVIEW / 'shapes.png'} and {PREVIEW / 'blend.png'}"
        )


if __name__ == "__main__":
    main()
