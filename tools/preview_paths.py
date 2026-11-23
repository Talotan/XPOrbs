"""Draws the three flight paths (Smooth, Chaos, Helix) from logic/OrbMath.lua for design review.

    uv run --with pillow python tools/preview_paths.py [output.png] [--gif [output.gif]]

PNG (default dist/paths-preview.png), one column per path, from a mob point at (40 %, 55 %) of a 1280x720 screen to
a bar point at (60 %, 4 %):
  row 1: the long flight, cropped to its bounding box, 14 orbs with the burst's start spread, each a faint line, a few
         dots and the snapshot at t = 0.55 with its two trail ghosts;
  row 2: a short 200 px flight in the same direction;
  row 3: the long flight as the stream after a Popstream (Nameplate) pop (tighter control points, stagger 0.08);
  row 4: three single orbs as thick lines (no start spread), so the shape of the path itself is visible.
GIF (default dist/paths-preview.gif): the three paths side by side, animated over the real flight time at 30 fps with
12 orbs each, trails, a dark background.
A dot's size and alpha follow the helix depth. The maths is the real OrbMath and mirrors Burst (the control-point
spread and launch stagger of OrbMath.PathShape); the fade-in and the shrink near the end are drawn too.
"""

import math
import random
import sys
from functools import cache
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

try:
    import lupa.lua51 as lupa_rt
except ImportError:  # pragma: no cover
    import lupa.luajit21 as lupa_rt

ROOT = Path(__file__).resolve().parent.parent
SCREEN_W, SCREEN_H = 1280, 720
GHOST_STEP = 0.015  # in progress, before easing (Orbs.lua GHOST_STEP)
ORB_RADIUS = 6.5  # px of a drawn orb (the art's soft rim makes the 28 px quad look about this big)
ORB_COLOUR = (190, 110, 255)
STRAND_COLOURS = ((190, 110, 255), (110, 210, 255), (255, 190, 100))
BACKGROUND = (16, 18, 28)
PATHS = ("smooth", "chaos", "helix")
PATH_TITLE = {"smooth": "Smooth", "chaos": "Chaos", "helix": "Helix"}
FLIGHT_TIME = 1.0  # s, the default flightTime
STAGGER = 0.15  # s, Orbs.lua STAGGER
START_RADIUS = 6
MARGIN = 110  # px around a flight's bounding box (the Chaos amplitude reaches about 90)
FPS = 30


def load_orbmath():
    lua = lupa_rt.LuaRuntime(unpack_returned_tuples=True)
    ns = lua.table()
    loader = lua.eval("function(src, name) return loadstring(src, name) end")
    chunk = loader(
        (ROOT / "logic" / "OrbMath.lua").read_text(encoding="utf-8"), "@OrbMath.lua"
    )
    chunk("XPOrbs", ns)
    return ns["OrbMath"]


def make_orbs(om, kind, start, end, count, rng, spread=True, popstream=False):
    """The orbs of one burst, spawned like Burst does: start disc, control point, path parameters, delay, duration.
    popstream mirrors the stream after a nameplate pop (control spread 0.45, lift 0.10, stagger 0.08, +0.30 s)."""
    control_scale, stagger_scale, duration_low, duration_span, _ring = om.PathShape(
        kind
    )
    base_spread, lift, stagger, extra = (
        (0.45, 0.10, 0.08, 0.30) if popstream else (None, None, STAGGER, 0.0)
    )
    pop_spread = (
        (base_spread or 1) * control_scale if control_scale != 1 else base_spread
    )
    handedness = -1 if kind == "helix" and rng.random() < 0.5 else 1
    orbs = []
    for index in range(1, count + 1):
        angle, radius = (
            rng.random() * math.tau,
            (START_RADIUS * math.sqrt(rng.random()) if spread else 0),
        )
        x0, y0 = (
            start[0] + math.cos(angle) * radius,
            start[1] + math.sin(angle) * radius,
        )
        c1x, c1y, _ = om.PopControl(index, count, x0, y0, rng.random, pop_spread, lift)
        distance = math.dist((x0, y0), end)
        params = tuple(om.PathParams(kind, index, distance, rng.random, handedness))
        order = rng.random()
        if stagger_scale != 1:
            order = (math.floor((index - 1) / 2) + order * 0.2) / math.floor(
                (count + 1) / 2
            )
        low, span = (duration_low, duration_span) if duration_low else (0.85, 0.3)
        orbs.append(
            {
                "kind": kind,
                "start": (x0, y0),
                "end": end,
                "control": (c1x, c1y),
                "params": params,
                "delay": order * stagger * stagger_scale + extra,
                "duration": FLIGHT_TIME * (low + span * rng.random()),
            }
        )
    return orbs


def flight_point(om, orb, t):
    """(x, y, size multiplier, alpha multiplier) at progress t: Orbs.lua flightPoint with the default ease."""
    x0, y0 = orb["start"]
    dx, dy = orb["end"]
    c1x, c1y = orb["control"]
    c2x, c2y = om.HomeControl(c1x, c1y, dx, dy, math.dist((x0, y0), (dx, dy)))
    perp, warp, size_mul, alpha_mul = om.PathOffset(orb["kind"], t, *orb["params"])
    x, y = om.Cubic(om.PopEase(t + warp, 0.5), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
    line_x, line_y = dx - x0, dy - y0
    length = math.hypot(line_x, line_y)
    if length > 1e-6:
        x -= line_y / length * perp
        y += line_x / length * perp
    return x, y, size_mul, alpha_mul


@cache
def glow_sprite(radius, alpha_steps, colour):
    """A soft round orb (bright core, falling to nothing at the rim) as an RGB image to add; alpha_steps is 0..20."""
    diameter = max(2, 2 * radius)
    falloff = (
        Image.radial_gradient("L")
        .resize((diameter, diameter))
        .point(lambda v: max(0, 255 - v) ** 2 // 255)
    )
    strength = alpha_steps / 20
    bands = [falloff.point(lambda v, c=c: int(v * c / 255 * strength)) for c in colour]
    return Image.merge("RGB", bands)


class Panel:
    """A drawing surface mapping world px (y up) to image px: `origin` is the world point at the bottom-left."""

    def __init__(self, size, origin, scale=1.0):
        self.image = Image.new("RGB", size, BACKGROUND)
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.size, self.origin, self.scale = size, origin, scale

    def px(self, x, y):
        return (x - self.origin[0]) * self.scale, self.size[1] - (
            y - self.origin[1]
        ) * self.scale

    def marker(self, point, colour):
        x, y = self.px(*point)
        self.draw.ellipse(
            [x - 5, y - 5, x + 5, y + 5], outline=colour + (255,), width=2
        )

    def dot(self, point, size_k=1.0, alpha_k=1.0, colour=ORB_COLOUR):
        """An orb as a radial-gradient sprite added to the image, so crossings white out like the game's glow."""
        x, y = self.px(point[0], point[1])
        radius = ORB_RADIUS * self.scale * size_k * point[2] * 1.6
        alpha = max(0.0, min(1.0, alpha_k * point[3]))
        if radius < 0.5 or alpha <= 0.01:
            return
        sprite = glow_sprite(round(radius), round(alpha * 20), colour)
        left, top = round(x) - sprite.width // 2, round(y) - sprite.height // 2
        box = (left, top, left + sprite.width, top + sprite.height)
        clipped = (
            max(box[0], 0),
            max(box[1], 0),
            min(box[2], self.size[0]),
            min(box[3], self.size[1]),
        )
        if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
            return
        sprite = sprite.crop(
            (
                clipped[0] - box[0],
                clipped[1] - box[1],
                clipped[2] - box[0],
                clipped[3] - box[1],
            )
        )
        self.image.paste(ImageChops.add(self.image.crop(clipped), sprite), clipped[:2])

    def label(self, text):
        self.draw.text(
            (8, 6), text, fill=(230, 230, 240, 255), font=ImageFont.load_default()
        )


def fit(start, end, margin=MARGIN):
    """origin and image size that hold the box around start and end plus a margin, at scale 1."""
    low = (min(start[0], end[0]) - margin, min(start[1], end[1]) - margin)
    high = (max(start[0], end[0]) + margin, max(start[1], end[1]) + margin)
    return low, (round(high[0] - low[0]), round(high[1] - low[1]))


def snapshot_panel(om, kind, start, end, label, seed, count=14, popstream=False):
    origin, size = fit(start, end)
    panel = Panel(size, origin)
    panel.marker(start, (120, 220, 140))
    panel.marker(end, (240, 200, 90))
    for orb in make_orbs(
        om, kind, start, end, count, random.Random(seed), popstream=popstream
    ):
        points = [flight_point(om, orb, i / 120) for i in range(121)]
        for a, b in pairwise(points):
            panel.draw.line(
                [panel.px(a[0], a[1]), panel.px(b[0], b[1])],
                fill=ORB_COLOUR + (38,),
                width=1,
            )
        for t in (0.15, 0.3, 0.45, 0.7, 0.85):
            panel.dot(flight_point(om, orb, t), 0.55, 0.5)
        for step, size_k, alpha_k in ((2, 0.70, 0.30), (1, 0.85, 0.55), (0, 1.0, 1.0)):
            panel.dot(flight_point(om, orb, 0.55 - step * GHOST_STEP), size_k, alpha_k)
    panel.label(label)
    return panel.image


def strand_panel(om, kind, start, end, label, seed):
    """Three single orbs, no start spread, as thick lines: width and alpha follow the depth."""
    origin, size = fit(start, end)
    panel = Panel(size, origin)
    panel.marker(start, (120, 220, 140))
    panel.marker(end, (240, 200, 90))
    rng = random.Random(seed)
    orbs = make_orbs(om, kind, start, end, 3, rng, spread=False)
    for orb, colour in zip(orbs, STRAND_COLOURS):
        points = [flight_point(om, orb, i / 200) for i in range(201)]
        for a, b in pairwise(points):
            width = max(1, round(5 * (a[2] + b[2]) / 2))
            alpha = int(255 * max(0.0, min(1.0, (a[3] + b[3]) / 2)))
            panel.draw.line(
                [panel.px(a[0], a[1]), panel.px(b[0], b[1])],
                fill=colour + (alpha,),
                width=width,
            )
    panel.label(label)
    return panel.image


def png(om, output):
    start = (SCREEN_W * 0.40, SCREEN_H * 0.55)
    end = (SCREEN_W * 0.60, SCREEN_H * 0.04)
    length = math.dist(start, end)
    short_end = (
        start[0] + (end[0] - start[0]) / length * 200,
        start[1] + (end[1] - start[1]) / length * 200,
    )
    columns = []
    for kind in PATHS:
        name = PATH_TITLE[kind]
        columns.append(
            [
                snapshot_panel(
                    om, kind, start, end, f"{name}: long flight ({length:.0f} px)", 11
                ),
                snapshot_panel(
                    om, kind, start, short_end, f"{name}: short flight (200 px)", 12
                ),
                snapshot_panel(
                    om,
                    kind,
                    start,
                    end,
                    f"{name}: after a Popstream (Nameplate) pop",
                    14,
                    popstream=True,
                ),
                strand_panel(
                    om,
                    kind,
                    start,
                    end,
                    f"{name}: three single orbs, no start spread",
                    13,
                ),
            ]
        )
    cell_w = max(img.width for col in columns for img in col)
    row_h = [max(col[row].height for col in columns) for row in range(4)]
    sheet = Image.new(
        "RGB", (len(columns) * (cell_w + 10) + 10, sum(row_h) + 10 * 5), (40, 42, 54)
    )
    for column, images in enumerate(columns):
        for row, image in enumerate(images):
            sheet.paste(
                image, (10 + column * (cell_w + 10), 10 + sum(row_h[:row]) + 10 * row)
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(output)


def gif(om, output, count=12):
    start = (SCREEN_W * 0.40, SCREEN_H * 0.55)
    end = (SCREEN_W * 0.60, SCREEN_H * 0.04)
    origin, size = fit(start, end)
    scale = 0.8
    size = (round(size[0] * scale), round(size[1] * scale))
    burst = {
        kind: make_orbs(om, kind, start, end, count, random.Random(21))
        for kind in PATHS
    }
    total = (
        max(o["delay"] + o["duration"] for orbs in burst.values() for o in orbs) + 0.35
    )
    frames = []
    for frame in range(int(total * FPS)):
        now = frame / FPS
        sheet = Image.new("RGB", (size[0] * 3 + 20, size[1] + 24), (40, 42, 54))
        for column, kind in enumerate(PATHS):
            panel = Panel(size, origin, scale)
            panel.marker(start, (120, 220, 140))
            panel.marker(end, (240, 200, 90))
            for orb in burst[kind]:
                t = (now - orb["delay"]) / orb["duration"]
                if not 0 < t < 1:
                    continue
                fade = min(1.0, t / 0.1)
                shrink = 1 - 0.4 * (t - 0.8) / 0.2 if t > 0.8 else 1.0
                for step, size_k, alpha_k in ((2, 0.70, 0.30), (1, 0.85, 0.55)):
                    if t - step * GHOST_STEP > 0:
                        panel.dot(
                            flight_point(om, orb, t - step * GHOST_STEP),
                            size_k * shrink,
                            alpha_k * fade,
                        )
                panel.dot(flight_point(om, orb, t), shrink, fade)
            panel.label(PATH_TITLE[kind])
            sheet.paste(panel.image, (column * (size[0] + 10), 12))
        frames.append(sheet.quantize(colors=64, method=Image.Quantize.MEDIANCUT))
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=[(30, 30, 40)[n % 3] for n in range(len(frames))],
        loop=0,
        optimize=True,
    )
    print(output, f"{output.stat().st_size / 1e6:.2f} MB", f"{len(frames)} frames")


def main():
    args = sys.argv[1:]
    make_gif = "--gif" in args
    paths = [Path(a) for a in args if a != "--gif"]
    om = load_orbmath()
    if make_gif:
        gif(om, paths[0] if paths else ROOT / "dist" / "paths-preview.gif")
    else:
        png(om, paths[0] if paths else ROOT / "dist" / "paths-preview.png")


if __name__ == "__main__":
    main()
