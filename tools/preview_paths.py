"""Draws the three flight paths (Smooth, Chaos, Helix) from logic/OrbMath.lua for design review.

    uv run --with pillow python tools/preview_paths.py [output.png] [--gif [output.gif]]

PNG (default dist/paths-preview.png), one column per path, from a mob point at (40 %, 55 %) of a 1280x720 screen to
a bar point at (60 %, 4 %):
  row 1: the long flight, cropped to its bounding box, 14 orbs with the burst's start spread, each a faint line, a few
         dots and the snapshot at t = 0.55 with its two trail ghosts;
  row 2: a short 200 px flight in the same direction;
  row 3: the long flight as the stream after a Popstream (Nameplate) pop (tighter control points, stagger 0.08);
  row 4: three single orbs as thick lines (no start spread), so the shape of the path itself is visible.
Scenario mode (`--scenarios [dir]`, default dist/): paths-scenarios.png, a grid of bar positions (bottom-centre default
UI, top-right DaylightUI-like, top-centre FlareUI-like, top edge EllesmereUI-like) by mob positions (centre-left,
centre, centre-right, unknown) with one column per path, on a 2560x1440 screen shown in UIParent units (1707x960),
the screen
border drawn so leaving it is obvious; and paths-starts.png comparing Popstream (Direct) at a detected vs an unknown
origin and the Helix start spread. These mirror the bow direction, control-point clamp and start shapes of Burst.
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
UIPARENT = (1707, 960)  # a 2560x1440 screen at UI scale 2/3: the units Burst works in
UNKNOWN_RX, UNKNOWN_RY = 0.064, 0.04  # Orbs.lua UNKNOWN: the unknown-origin ellipse, fractions of the screen
HELIX_LINE, HELIX_LINE_UNKNOWN, POP_WIDEN, HELIX_RING_WIDEN = 8, 18, 1.6, 1.4
# Orbs.lua SP_PROFILE: per-orb bloom seconds (nearest to the bar shortest; the launch is its end), ring radii (0.84 x
# the Nameplate pop's 30..55), partial ease-out weight, the widened ring's x-radius cap
SP_BLOOM_MIN, SP_BLOOM_SPAN, SP_RING_MIN, SP_RING_MAX, SP_EASE_OUT, SP_WIDTH_CAP = 0.20, 0.06, 25, 46, 0.5, 64
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


def make_orbs(om, kind, start, end, count, rng, spread=True, popstream=False, screen=None, origin="point"):
    """The orbs of one burst, spawned like Burst does: start disc, control point, path parameters, delay, duration.
    popstream mirrors the stream after a nameplate pop (control spread 0.45, lift 0.10, stagger 0.08, +0.30 s).
    screen=(w, h) switches on what Burst does for the screen edge (bow direction, control-point clamp, the helix's
    start line); origin is "point" (detected) or "unknown" (the ellipse; a short line for the helix)."""
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
    side = om.BowSide(start[0], start[1], end[0], end[1], *screen) if screen else 1
    for index in range(1, count + 1):
        angle, radius = (
            rng.random() * math.tau,
            (START_RADIUS * math.sqrt(rng.random()) if spread else 0),
        )
        x0, y0 = (
            start[0] + math.cos(angle) * radius,
            start[1] + math.sin(angle) * radius,
        )
        if screen and kind == "helix":
            half = HELIX_LINE_UNKNOWN if origin == "unknown" else HELIX_LINE
            ax, ay = end[0] - start[0], end[1] - start[1]
            norm = math.hypot(ax, ay) or 1
            ax, ay = ax / norm, ay / norm
            across, along = (rng.random() * 2 - 1) * half, (rng.random() * 2 - 1) * 2
            x0, y0 = start[0] - ay * across + ax * along, start[1] + ax * across + ay * along
        elif origin == "unknown":
            angle, radius = rng.random() * math.tau, math.sqrt(rng.random())
            x0 = start[0] + math.cos(angle) * radius * UNKNOWN_RX * UIPARENT[0]
            y0 = start[1] + math.sin(angle) * radius * UNKNOWN_RY * UIPARENT[1]
        bow = tuple(om.BowVector(x0, y0, end[0], end[1], *screen, side)) if screen else (0, 1)
        c1x, c1y, _ = om.PopControl(index, count, x0, y0, rng.random, pop_spread, lift, *bow)
        distance = math.dist((x0, y0), end)
        params = tuple(om.PathParams(kind, index, distance, rng.random, handedness))
        margin = (0.04 * screen[1] + abs(params[0])) if screen else 0
        if screen:
            c1x, c1y = om.ClampToScreen(c1x, c1y, screen[0], screen[1], margin, end[0], end[1])
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
                "bow": bow,
                "screen": screen,
                "margin": margin,
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
    c2x, c2y = om.HomeControl(c1x, c1y, dx, dy, math.dist((x0, y0), (dx, dy)), *orb["bow"])
    screen = orb["screen"]
    if screen:
        c2x, c2y = om.ClampToScreen(c2x, c2y, screen[0], screen[1], orb["margin"], dx, dy)
    perp, warp, size_mul, alpha_mul = om.PathOffset(orb["kind"], t, *orb["params"])
    x, y = om.Cubic(om.PopEase(t + warp, 0.5), x0, y0, c1x, c1y, c2x, c2y, dx, dy)
    line_x, line_y = dx - x0, dy - y0
    length = math.hypot(line_x, line_y)
    if length > 1e-6:
        x -= line_y / length * perp
        y += line_x / length * perp
    if screen:  # Burst's last resort: the drawn point stays on screen
        x, y = om.ClampToScreen(x, y, screen[0], screen[1], 0)
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



BARS = (
    ("bottom-centre (default UI)", (0.5, 0.03)),
    ("top-right (DaylightUI-like)", (0.86, 0.965)),
    ("top-centre (FlareUI-like)", (0.5, 0.985)),
    ("top edge (EllesmereUI-like)", (0.35, 1 - 3 / 960)),
)
MOBS = (
    ("mob centre-left", (0.35, 0.55)),
    ("mob centre", (0.5, 0.55)),
    ("mob centre-right", (0.65, 0.55)),
    ("mob unknown", (0.5, 0.65)),
)


def draw_flights(panel, om, orbs):
    """Faint flight lines plus the t = 0.55 snapshot with its trail ghosts."""
    for orb in orbs:
        points = [flight_point(om, orb, i / 100) for i in range(101)]
        for a, b in pairwise(points):
            panel.draw.line([panel.px(a[0], a[1]), panel.px(b[0], b[1])], fill=ORB_COLOUR + (60,), width=1)
        for step, size_k, alpha_k in ((2, 0.70, 0.30), (1, 0.85, 0.55), (0, 1.0, 1.0)):
            panel.dot(flight_point(om, orb, 0.55 - step * GHOST_STEP), size_k, alpha_k)


def screen_panel(om, kind, start, end, label, seed, scale, origin="point", count=10):
    """The whole screen at `scale`, the border in red so leaving it is obvious."""
    width, height = UIPARENT
    panel = Panel((round(width * scale), round(height * scale)), (0, 0), scale)
    panel.marker(start, (120, 220, 140))
    panel.marker(end, (240, 200, 90))
    draw_flights(panel, om, make_orbs(om, kind, start, end, count, random.Random(seed), screen=UIPARENT, origin=origin))
    panel.draw.rectangle([0, 0, panel.size[0] - 1, panel.size[1] - 1], outline=(230, 60, 60, 255), width=2)
    panel.label(label)
    return panel.image


def streampop_panel(om, kind, start, end, label, seed, scale, origin):
    """Popstream (Direct): a fixed pop at `start`, a ring of 25..46 px (stretched horizontally, capped, when unknown; for a
    helix halved, and stretched 1.4x when detected) that each orb leaves at the end of its own bloom, then the stream. Mirrors SP_PROFILE.plan and the Burst blend."""
    width, height = UIPARENT
    panel = Panel((round(width * scale), round(height * scale)), (0, 0), scale)
    panel.marker(start, (120, 220, 140))
    panel.marker(end, (240, 200, 90))
    rng = random.Random(seed)
    count = 12
    ring_scale = 0.5 if kind == "helix" else 1
    widen = POP_WIDEN if origin == "unknown" else (HELIX_RING_WIDEN if kind == "helix" else 1)
    side = om.BowSide(start[0], start[1], end[0], end[1], width, height)
    control_scale = om.PathShape(kind)[0]
    handedness = -1 if kind == "helix" and rng.random() < 0.5 else 1
    rings = []
    for index in range(1, count + 1):
        ring_angle = om.RingAngle(index, count, rng.random)
        radius = (SP_RING_MIN + rng.random() * (SP_RING_MAX - SP_RING_MIN)) * ring_scale
        ring_width = min(radius * widen, max(radius, SP_WIDTH_CAP))
        ring = (start[0] + math.cos(ring_angle) * ring_width, start[1] + math.sin(ring_angle) * radius)
        rings.append((ring_angle, ring))
    # bloom durations: nearest ring point to the bar blooms shortest; each orb launches the moment its bloom ends, at
    # its ring point
    by_distance = sorted(range(count), key=lambda i: math.hypot(end[0] - rings[i][1][0], end[1] - rings[i][1][1]))
    blooms = {i: SP_BLOOM_MIN + SP_BLOOM_SPAN * rank / (count - 1) for rank, i in enumerate(by_distance)}
    orbs = []
    for index in range(1, count + 1):
        ring_angle, ring = rings[index - 1]
        x0, y0 = ring
        vx, vy = end[0] - x0, end[1] - y0
        length = math.hypot(vx, vy)
        vx, vy = vx / length, vy / length
        reach = (45 + rng.random() * 55) * 0.45 * 2.2 * control_scale
        c1 = (
            x0 + (math.cos(ring_angle) * 0.6 + vx * 0.4) * reach,
            y0 + (math.sin(ring_angle) * 0.6 + vy * 0.4) * reach,
        )
        bow = tuple(om.BowVector(x0, y0, end[0], end[1], width, height, side))
        params = tuple(om.PathParams(kind, index, length, rng.random, handedness))
        margin = 0.04 * height + abs(params[0])
        c1 = tuple(om.ClampToScreen(c1[0], c1[1], width, height, margin, end[0], end[1]))
        orbs.append({"kind": kind, "start": (x0, y0), "end": end, "control": c1, "bow": bow, "screen": UIPARENT,
                     "margin": margin, "params": params})
        panel.dot((ring[0], ring[1], 1, 1), 0.5, 0.6, (110, 210, 255))
    draw_flights(panel, om, orbs)
    panel.draw.rectangle([0, 0, panel.size[0] - 1, panel.size[1] - 1], outline=(230, 60, 60, 255), width=2)
    panel.label(label)
    return panel.image


def sheet_of(rows, output):
    """Paste rows of equally sized images into one PNG."""
    cell_w, cell_h = rows[0][0].size
    sheet = Image.new("RGB", (len(rows[0]) * (cell_w + 8) + 8, len(rows) * (cell_h + 8) + 8), (40, 42, 54))
    for row, images in enumerate(rows):
        for column, image in enumerate(images):
            sheet.paste(image, (8 + column * (cell_w + 8), 8 + row * (cell_h + 8)))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(output)


def scenarios(om, directory):
    width, height = UIPARENT
    rows = []
    for bar_name, bar in BARS:
        end = (bar[0] * width, bar[1] * height)
        for mob_name, mob in MOBS:
            start = (mob[0] * width, mob[1] * height)
            origin = "unknown" if mob_name.endswith("unknown") else "point"
            rows.append(
                [
                    screen_panel(om, kind, start, end, f"{PATH_TITLE[kind]}: {bar_name}, {mob_name}", 5, 0.22, origin)
                    for kind in PATHS
                ]
            )
    sheet_of(rows, directory / "paths-scenarios.png")

    # Popstream (Direct), detected vs unknown origin, then the Direct Stream's start spread (smooth vs helix)
    end, start, scale = (0.86 * width, 0.965 * height), (0.4 * width, 0.5 * height), 0.35
    rows = [
        [
            streampop_panel(om, kind, start, end, f"Popstream (Direct), {PATH_TITLE[kind]}, {name} origin", 7, scale, o)
            for name, o in (("detected", "point"), ("unknown", "unknown"))
        ]
        for kind in PATHS
    ]
    for kind in ("smooth", "helix"):
        rows.append(
            [
                screen_panel(om, kind, start, end, f"Direct Stream, {PATH_TITLE[kind]}, {name} origin", 8, scale, o, 20)
                for name, o in (("detected", "point"), ("unknown", "unknown"))
            ]
        )
    sheet_of(rows, directory / "paths-starts.png")


def main():
    args = sys.argv[1:]
    make_gif = "--gif" in args
    paths = [Path(a) for a in args if not a.startswith("--")]
    om = load_orbmath()
    if "--scenarios" in args:
        scenarios(om, paths[0] if paths else ROOT / "dist")
    elif make_gif:
        gif(om, paths[0] if paths else ROOT / "dist" / "paths-preview.gif")
    else:
        png(om, paths[0] if paths else ROOT / "dist" / "paths-preview.png")


if __name__ == "__main__":
    main()
