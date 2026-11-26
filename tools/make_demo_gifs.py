"""Marketing GIFs for the CurseForge page, made from the real addon code.

The addon's Lua runs unchanged in the test harness (lupa + the WoW stubs in tests/). Every frame, each shown stub
texture is read back (art path, blend mode, draw layer, vertex colour, alpha, size, position, rotation, texcoord
window) and composited with the real media/*.tga art, the way the game draws it: vertex colour multiplies RGB, ADD is
dst + src.rgb * src.a, BLEND is plain alpha-over, draw layer then sublayer then creation order, NEAREST art (Retro)
scaled with nearest-neighbour, the rest bilinear.

  flight-paths.gif  the three flight pathings (Smooth, Chaos, Helix), one real burst each (`Orbs:Burst`, Direct Stream
                    style, 6 orbs of which 2 rested, Relative speed at 1.0 s so the path shape has time to show), all
                    other settings default
  orb-shapes.gif    the four orb shapes (Starlight, Bubble, Retro, Crackle) as the options preview draws them
                    (ShapePreview, tidy layout, 6 orbs, rested slots in the rested colour), idle animations running

Run from the repo root (output goes to dist/, with a few still PNGs next to the GIFs for review):

    uv run --with pillow --with numpy python tools/make_demo_gifs.py [flight|shapes|all] [--out DIR]

Needs the dev environment (lupa) as the tests do; pillow and numpy come in through --with.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import lupa.lua51 as lupa_rt
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
MEDIA = ROOT / "media"

FPS = 25
SIM_DT = 0.01  # the Lua side is stepped finer than the GIF frame, so timers behave as at a high game frame rate
STEPS_PER_FRAME = round(1 / FPS / SIM_DT)
GOLD = (255, 209, 0)  # the WoW UI text colour

# ---------------------------------------------------------------- the Lua runtime

LUA_HELPERS = """
-- stamp every texture call with a global sequence number, so "SetTexture or SetColorTexture, whichever came last" is known
local fm = getmetatable(UIParent).__index
local seq = 0
for _, name in ipairs({ "SetTexture", "SetColorTexture" }) do
    local base = fm[name]
    fm[name] = function(self, ...)
        seq = seq + 1
        self.seq = self.seq or {}
        self.seq[name] = seq
        return base(self, ...)
    end
end
"""


class Game:
    """The addon loaded on the stub client, the way tests/test_m5.py build() does it."""

    def __init__(self, seed: int):
        lua = lupa_rt.LuaRuntime(unpack_returned_tuples=True)
        self.lua = lua
        ns = lua.table()
        ns["fixtureDir"] = str(TESTS / "fixtures").replace("\\", "/")
        self.ns = ns
        loader = lua.eval("function(src, name) return loadstring(src, name) end")

        def load(path: Path, chunkname: str):
            fn = loader(path.read_text(encoding="utf-8"), "@" + chunkname)
            if isinstance(fn, tuple):
                raise RuntimeError(f"{chunkname}: {fn[1]}")
            if fn is None:
                raise RuntimeError(f"failed to compile {chunkname}")
            return fn

        load(TESTS / "wowstub.lua", "wowstub.lua")(ns)
        for stub in ("stubs_m2.lua", "stubs_m5.lua", "stubs_m3.lua"):
            load(TESTS / stub, stub)(ns)
        lua.execute(LUA_HELPERS)
        for line in (ROOT / "XPOrbs.toc").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if (
                line
                and not line.startswith("#")
                and not line.startswith("Libs")
                and line.endswith(".lua")
            ):
                rel = line.replace("\\", "/")
                load(ROOT / rel, rel)("XPOrbs", ns)
        ns.fire("ADDON_LOADED", "XPOrbs")
        self.G = lua.globals()
        self.stub = ns.stub
        self.db = self.G.XPOrbsDB
        self.orbs = ns.Orbs
        lua.execute(f"math.randomseed({seed})")

    def tick(self, dt: float = SIM_DT, n: int = 1):
        for _ in range(n):
            self.stub.tick(dt)


def lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)]


# ---------------------------------------------------------------- reading the textures

LAYER = {"BACKGROUND": 0, "BORDER": 1, "ARTWORK": 2, "OVERLAY": 3, "HIGHLIGHT": 4}


class Tex:
    """One shown stub texture, read back."""

    __slots__ = (
        "path",
        "color",
        "blend",
        "layer",
        "sub",
        "order",
        "vc",
        "alpha",
        "x",
        "y",
        "w",
        "h",
        "rot",
        "tc",
        "nearest",
    )


def num(v, default=0.0):
    return float(v) if v is not None else default


class Reader:
    """Reads the shown textures anchored to one frame (the orb overlay, or the preview area)."""

    def __init__(self, game: Game, frame):
        self.game = game
        self.rawequal = game.lua.eval("rawequal")
        self.frame = frame

    def read(self) -> list[Tex]:
        out = []
        for order, t in enumerate(lua_list(self.game.stub.frames)):
            if t.kind != "Texture" or not t.shown or t.parentFrame is None:
                continue
            if not self.rawequal(t.parentFrame, self.frame):
                continue
            if (
                not t.points
                or len(t.points) < 1
                or not self.rawequal(t.points[1][2], self.frame)
            ):
                continue
            c = t.calls
            if c is None:
                continue
            tx = Tex()
            tx.order = order
            tx.alpha = num(t.alpha, 1.0)
            st, sc = c["SetTexture"], c["SetColorTexture"]
            seq = t.seq
            seq_t = (
                num(seq["SetTexture"], -1)
                if seq and seq["SetTexture"] is not None
                else -1
            )
            seq_c = (
                num(seq["SetColorTexture"], -1)
                if seq and seq["SetColorTexture"] is not None
                else -1
            )
            tx.path, tx.color, tx.nearest = None, None, False
            if sc is not None and seq_c > seq_t:
                tx.color = tuple(num(sc[i], 1.0) for i in range(1, 5))
            elif st is not None:
                tx.path = str(st[1])
                tx.nearest = st[4] is not None and str(st[4]) == "NEAREST"
            else:
                continue
            bm = c["SetBlendMode"]
            tx.blend = str(bm[1]) if bm is not None else "BLEND"
            dl = c["SetDrawLayer"]
            if dl is not None:
                tx.layer, tx.sub = LAYER[str(dl[1])], int(num(dl[2]))
            else:  # only the arrival flash is never given a layer; it was created in OVERLAY
                tx.layer, tx.sub = LAYER["OVERLAY"], 0
            vc = c["SetVertexColor"]
            tx.vc = (
                (num(vc[1], 1), num(vc[2], 1), num(vc[3], 1), num(vc[4], 1))
                if vc is not None
                else (1, 1, 1, 1)
            )
            p = t.points[1]
            tx.x, tx.y = num(p[4]), num(p[5])
            tx.w, tx.h = num(t.width), num(t.height)
            r = c["SetRotation"]
            tx.rot = num(r[1]) if r is not None else 0.0
            tcd = c["SetTexCoord"]
            tx.tc = (
                tuple(num(tcd[i]) for i in range(1, 5))
                if tcd is not None and tcd[4] is not None
                else (0, 1, 0, 1)
            )
            out.append(tx)
        out.sort(key=lambda a: (a.layer, a.sub, a.order))
        return out


# ---------------------------------------------------------------- compositing

_art: dict[str, Image.Image] = {}


def art(path: str) -> Image.Image:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name not in _art:
        _art[name] = Image.open(MEDIA / f"{name}.tga").convert("RGBA")
    return _art[name]


def premultiplied_tile(tx: Tex, scale: float):
    """(tile uint8 RGBA premultiplied, tile left, top) for one textured quad, subpixel placed and rotated."""
    w, h = tx.w * scale, tx.h * scale
    wd, hd = max(1, round(w)), max(1, round(h))
    img = art(tx.path)
    left, right, top, bottom = tx.tc
    iw, ih = img.size
    img = img.crop(
        (round(left * iw), round(top * ih), round(right * iw), round(bottom * ih))
    )
    img = img.resize((wd, hd), Image.NEAREST if tx.nearest else Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr[..., :3] *= arr[..., 3:4]
    return arr, wd, hd


def tile_place(arr, wd, hd, cx, cy, rot, nearest):
    """Rotate (CCW, radians) about the centre and place at the sub-pixel centre (cx, cy); -> (tile, x0, y0)."""
    if abs(rot) < 1e-6 and nearest:
        x0, y0 = round(cx - wd / 2), round(cy - hd / 2)
        return arr, x0, y0
    diag = math.hypot(wd, hd)
    size = math.ceil(diag) + 3
    x0, y0 = math.floor(cx - size / 2), math.floor(cy - size / 2)
    ccx, ccy = cx - x0, cy - y0  # the quad's centre in tile coordinates (continuous)
    cos, sin = math.cos(rot), math.sin(rot)
    # output pixel (u, v) -> source (x, y): rotate by -rot (y points down, a CCW image turn), then shift to the source
    a, b = cos, sin
    d, e = -sin, cos
    c = wd / 2 - (a * ccx + b * ccy)
    f = hd / 2 - (d * ccx + e * ccy)
    out = np.empty((size, size, 4), dtype=np.float32)
    for ch in range(4):
        band = Image.fromarray(arr[..., ch], "F")
        res = band.transform(
            (size, size),
            Image.AFFINE,
            (a, b, c, d, e, f),
            resample=Image.NEAREST if nearest else Image.BILINEAR,
        )
        out[..., ch] = np.asarray(res)
    return out, x0, y0


def blend_into(canvas, tile, x0, y0, tx: Tex):
    """canvas float32 HxWx3 (0..1); tile premultiplied float RGBA."""
    height, width = canvas.shape[:2]
    th, tw = tile.shape[:2]
    cx0, cy0 = max(x0, 0), max(y0, 0)
    cx1, cy1 = min(x0 + tw, width), min(y0 + th, height)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    sub_tile = tile[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0]
    dst = canvas[cy0:cy1, cx0:cx1]
    vr, vg, vb, va = tx.vc
    k = tx.alpha * va
    src = sub_tile[..., :3] * np.array([vr, vg, vb], dtype=np.float32) * k
    if tx.blend == "ADD":
        dst += src
    else:
        dst *= 1.0 - sub_tile[..., 3:4] * k
        dst += src


def draw_texture(canvas, tx: Tex, ox: float, oy: float, scale: float):
    """Draw one texture; (ox, oy) is where the anchor's origin is on the canvas, y of the texture counts upwards."""
    if tx.alpha <= 0.001 or tx.w <= 0 or tx.h <= 0:
        return
    cx, cy = ox + tx.x * scale, oy - tx.y * scale
    if tx.color is not None:
        w, h = max(1, round(tx.w * scale)), max(1, round(tx.h * scale))
        x0, y0 = round(cx - w / 2), round(cy - h / 2)
        r, g, b, a = tx.color
        tile = np.empty((h, w, 4), dtype=np.float32)
        tile[..., 0], tile[..., 1], tile[..., 2], tile[..., 3] = r * a, g * a, b * a, a
        blend_into(canvas, tile, x0, y0, tx)
        return
    arr, wd, hd = premultiplied_tile(tx, scale)
    tile, x0, y0 = tile_place(arr, wd, hd, cx, cy, tx.rot, tx.nearest)
    blend_into(canvas, tile, x0, y0, tx)


def composite(canvas, textures, ox, oy, scale):
    for tx in textures:
        draw_texture(canvas, tx, ox, oy, scale)


# ---------------------------------------------------------------- drawing helpers

_font_cache: dict = {}


def font(size: int, bold=True):
    key = (size, bold)
    if key not in _font_cache:
        names = (
            ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
        )
        names += ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
        for n in names:
            try:
                _font_cache[key] = ImageFont.truetype(n, size)
                break
            except OSError:
                continue
        else:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def night_background(
    width: int, height: int, seed: int, stars: int = 14, noise: bool = True
) -> np.ndarray:
    """A soft vertical gradient suggesting a night sky over a dark ground, a faint vignette and a few dim stars."""
    ys = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    top = np.array([0.045, 0.055, 0.115], dtype=np.float32)
    mid = np.array([0.075, 0.070, 0.150], dtype=np.float32)
    low = np.array([0.050, 0.045, 0.085], dtype=np.float32)
    grad = np.where(
        ys < 0.7, top + (mid - top) * (ys / 0.7), mid + (low - mid) * ((ys - 0.7) / 0.3)
    )
    img = np.broadcast_to(grad, (height, width, 3)).copy()
    xs = np.linspace(-1, 1, width, dtype=np.float32)[None, :, None]
    yy = np.linspace(-1, 1, height, dtype=np.float32)[:, None, None]
    img *= 1.0 - 0.22 * np.clip(xs**2 + yy**2 - 0.4, 0, 1)
    rng = np.random.default_rng(seed)
    for _ in range(stars):
        sx, sy = (
            int(rng.integers(2, width - 2)),
            int(rng.integers(2, int(height * 0.7))),
        )
        img[sy, sx] += rng.uniform(0.10, 0.28)
    # fixed, seeded +-1/255 noise (identical every frame) to break up the gradient banding
    if noise:
        img += (rng.integers(-1, 2, size=(height, width, 1)) / 255.0).astype(np.float32)
    return img


def to_pil(canvas: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def draw_label(img: Image.Image, text: str, cx: int, y: int, size: int = 15):
    d = ImageDraw.Draw(img)
    f = font(size)
    w = d.textlength(text, font=f)
    x = cx - w / 2
    d.text((x + 1, y + 1), text, font=f, fill=(0, 0, 0))  # WoW text has a drop shadow
    d.text((x, y), text, font=f, fill=GOLD)


def to_gif(frames: list[Image.Image], path: Path, fps: int, colors: int = 255):
    """One shared adaptive palette for the whole sequence, no dithering (a static background stays still).

    The palette is built from every frame, but only from the pixels that differ from the last frame (what moves: orbs,
    trails, glow) plus that one frame whole, so a mostly static picture does not spend the palette on its background.
    """
    arrs = [np.asarray(f) for f in frames]
    ref = arrs[-1]
    picked = [ref.reshape(-1, 3)]
    for a in arrs[:-1]:
        moved = np.any(a != ref, axis=2)
        picked.append(a[moved])
    flat = np.concatenate(picked)
    width = 1024
    rows = -(-len(flat) // width)
    flat = np.concatenate(
        [flat, np.zeros((rows * width - len(flat), 3), dtype=np.uint8)]
    )
    mosaic = Image.fromarray(flat.reshape(rows, width, 3), "RGB")
    pal = mosaic.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE)
    q = [f.quantize(palette=pal, dither=Image.NONE) for f in frames]
    q[0].save(
        path,
        save_all=True,
        append_images=q[1:],
        duration=round(1000 / fps),
        loop=0,
        optimize=False,
        disposal=1,
    )


# ---------------------------------------------------------------- GIF 1: flight paths

PANEL_W, PANEL_H = 220, 352  # px on the GIF (1 UI unit = 1 px)
SIM_W, SIM_H = PANEL_W, PANEL_H  # the simulated screen one panel shows
PATHS = [("smooth", "Smooth"), ("chaos", "Chaos"), ("helix", "Helix")]
TAIL = 0.5  # seconds of rest after the last orb has gone
BAR = {"left": 24, "bottom": 18, "width": SIM_W - 48, "height": 11}
MOB = (0.22 * SIM_W, 0.86 * SIM_H)  # y up, as the addon uses
XP_FRACTION = (
    0.85  # where the orbs land (the bar's fill edge at the end of the arrivals)
)
FILL_STEP = 0.03  # the bar's fill grows by this much over the arrivals, then eases back
N_ORBS, N_RESTED = 6, 2  # 4 normal + 2 rested, like the shapes GIF; 3 Helix pairs
PLATE_GAP, LABEL_H = 8, 28


def flight_runtime(seed: int):
    g = Game(seed)
    g.G.UIParent.width, g.G.UIParent.height = SIM_W, SIM_H
    g.stub.makeBar(
        "MainStatusTrackingBarContainer",
        BAR["left"],
        BAR["bottom"],
        BAR["width"],
        BAR["height"],
        True,
    )
    g.stub.xp, g.stub.xpMax = XP_FRACTION * 1000, 1000
    g.db.unknownOrigin = "off"
    g.db.flightMode = "time"  # the addon's Relative speed ("time"), 1.0 s flights
    g.db.flightTime = 1.0
    return g


def fire_burst(g: Game, path: str):
    """A Direct Stream test burst of N_ORBS (N_RESTED rested) at the chosen mob, on the given flight path."""
    opts = g.lua.table_from(
        {
            "x": MOB[0],
            "y": MOB[1],
            "ex": MOB[0],
            "ey": MOB[1],
            "est": "mouseover",
            "estW": 1,
            "n": N_ORBS,
            "scale": 1,
            "nPurple": N_RESTED,
            "kind": "test",
            "style": "stream",
            "path": path,
        }
    )
    g.orbs.Burst(g.orbs, opts)


def smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def draw_xp_bar(canvas: np.ndarray, fraction: float):
    """The Blizzard-style bar: dark track, purple fill to `fraction`, segment ticks (UI units = px, y up)."""
    height = canvas.shape[0]
    img = Image.new("RGB", (canvas.shape[1], height))
    d = ImageDraw.Draw(img)
    left, bottom = BAR["left"], height - BAR["bottom"]
    right, top = left + BAR["width"], bottom - BAR["height"]
    fill_to = left + BAR["width"] * fraction
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle([left - 1, top - 1, right, bottom], fill=255)
    d.rectangle([left - 1, top - 1, right, bottom], fill=(64, 52, 80))
    d.rectangle([left, top, right - 1, bottom - 1], fill=(8, 6, 14))
    d.rectangle([left, top, fill_to, bottom - 1], fill=(138, 24, 150))
    d.rectangle([left, top, fill_to, top + 1], fill=(176, 70, 188))
    d.rectangle([left, bottom - 2, fill_to, bottom - 1], fill=(92, 10, 104))
    for i in range(1, 10):
        x = left + BAR["width"] * i / 10
        d.line([x, top, x, bottom - 1], fill=(20, 14, 30))
    m = (np.asarray(mask, dtype=np.float32) / 255.0)[..., None]
    canvas[:] = canvas * (1 - m) + (np.asarray(img, dtype=np.float32) / 255.0) * m


def static_scene(width: int, height: int) -> np.ndarray:
    """RGBA overlay (0..1) of what never changes in a flight panel: the ground ring and a dead mob's nameplate."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mx, my = MOB[0], height - MOB[1]
    d.ellipse([mx - 11, my + 6, mx + 11, my + 14], outline=(200, 200, 230, 64), width=1)
    bx0, by0 = round(mx - 28), round(my - 16)
    d.rectangle([bx0, by0, bx0 + 55, by0 + 4], fill=(0, 0, 0, 255))
    d.rectangle(
        [bx0 + 1, by0 + 1, bx0 + 54, by0 + 3], fill=(58, 22, 22, 255)
    )  # health emptied: it died
    f = font(11, bold=False)
    name = "Kobold Miner"
    tw = d.textlength(name, font=f)
    tx, ty = mx - tw / 2, by0 - 15
    d.text((tx + 1, ty + 1), name, font=f, fill=(0, 0, 0, 255))
    d.text((tx, ty), name, font=f, fill=(255, 255, 255, 255))
    return np.asarray(img, dtype=np.float32) / 255.0


def plate_background(total_w, total_h, origins, plate_w, plate_h, seed):
    """The night background with one slightly darker rounded plate per panel."""
    bg = night_background(total_w, total_h, seed=seed, stars=30)
    plate = Image.new("L", (total_w, total_h), 0)
    pd = ImageDraw.Draw(plate)
    for x0, y0 in origins:
        pd.rounded_rectangle(
            [x0, y0, x0 + plate_w - 1, y0 + plate_h - 1], radius=8, fill=255
        )
    pm = (np.asarray(plate, dtype=np.float32) / 255.0)[..., None]
    return bg * (1 - 0.30 * pm)


def is_flash(t) -> bool:
    return (t.path or "").endswith("flash")


def make_flight(out: Path):
    games = [flight_runtime(seed=11 + i) for i in range(len(PATHS))]
    target = games[0].ns.Target
    dx, dy = (float(v) for v in target.GetDestination(target, False, False)[:2])
    print(
        f"flight: destination ({dx:.1f}, {dy:.1f}), mob ({MOB[0]:.1f}, {MOB[1]:.1f}), screen {SIM_W}x{SIM_H}"
    )
    for g, (path, _) in zip(games, PATHS):
        fire_burst(g, path)
    readers = [Reader(g, g.orbs.overlay) for g in games]
    # play the burst out, keeping what each frame draws (the bar and the sheet are composed afterwards)
    seen = []  # per frame: the textures of each panel
    for _ in range(round(4.0 * FPS)):
        seen.append([rd.read() for rd in readers])
        for g in games:
            g.tick(SIM_DT, STEPS_PER_FRAME)
    active = [i for i, panels in enumerate(seen) if any(panels)]
    orb_frames = [
        i
        for i, panels in enumerate(seen)
        if any(not is_flash(t) for p in panels for t in p)
    ]
    first_flash = min(
        (
            i
            for i, panels in enumerate(seen)
            if any(is_flash(t) for p in panels for t in p)
        )
    )
    last_orb = max(orb_frames)
    n_frames = max(active) + 1 + round(TAIL * FPS)
    print(
        f"flight: {len(active)} of {n_frames} frames show orbs or glow ({len(active) / n_frames:.0%}); "
        f"loop {n_frames / FPS:.2f} s; first flash frame {first_flash}, last orb frame {last_orb}"
    )

    origins = [
        (PLATE_GAP + i * (PANEL_W + PLATE_GAP), PLATE_GAP) for i in range(len(PATHS))
    ]
    plate_h = LABEL_H + PANEL_H
    total_w = len(PATHS) * PANEL_W + (len(PATHS) + 1) * PLATE_GAP
    total_h = plate_h + 2 * PLATE_GAP
    sheet_bg = plate_background(total_w, total_h, origins, PANEL_W, plate_h, seed=21)
    scene = static_scene(PANEL_W, PANEL_H)
    base_fill = XP_FRACTION - FILL_STEP
    frames = []
    for fi in range(n_frames):
        if fi < first_flash:
            lift = 0.0
        elif fi <= last_orb:
            lift = smooth((fi - first_flash) / max(1, last_orb - first_flash))
        else:
            lift = 1.0 - smooth((fi - last_orb) / max(1, n_frames - 1 - last_orb))
        canvas = sheet_bg.copy()
        for i, (x0, y0) in enumerate(origins):
            region = np.ascontiguousarray(
                canvas[y0 + LABEL_H : y0 + plate_h, x0 : x0 + PANEL_W]
            )
            draw_xp_bar(region, base_fill + FILL_STEP * lift)
            a = scene[..., 3:4]
            region = region * (1 - a) + scene[..., :3] * a
            composite(region, seen[fi][i], 0, PANEL_H, 1.0)
            canvas[y0 + LABEL_H : y0 + plate_h, x0 : x0 + PANEL_W] = region
        img = to_pil(canvas)
        for i, (_, label) in enumerate(PATHS):
            draw_label(img, label, origins[i][0] + PANEL_W // 2, origins[i][1] + 5)
        frames.append(img)
    to_gif(frames, out / "flight-paths.gif", FPS)
    frames[max(1, first_flash // 2)].save(out / "flight-paths-frame08.png")
    frames[(first_flash + last_orb) // 2].save(out / "flight-paths-mid.png")
    frames[last_orb].save(out / "flight-paths-late.png")
    # max over time: every orb position at once, to judge the paths (Smooth an arc family, Chaos weaving, Helix pairs)
    trace = np.max(np.stack([np.asarray(f) for f in frames]), axis=0)
    Image.fromarray(trace).save(out / "flight-paths-trace.png")


# ---------------------------------------------------------------- GIF 2: orb shapes

SHAPES = [
    ("starlight", "Starlight"),
    ("bubble", "Bubble"),
    ("retro", "Retro"),
    ("crackle", "Crackle"),
]
SHAPE_SCALE = 2  # px on the GIF per UI unit (a Retro cell is then whole px too)
LOOP = 2.0
AREA_W = 140  # UI units shown of the preview's orb area (it is 184 wide; six orbs need about 100), as tall as the window


def preview_area(g: Game):
    """The preview's orb area frame (named `box` before the rename to `orbArea`)."""
    sp = g.ns.ShapePreview
    return sp.orbArea if sp.orbArea is not None else sp.box


def shape_runtime(shape: str, seed: int):
    g = Game(seed)
    g.G.SettingsPanel = g.lua.eval("{}")  # the preview docks to the settings panel
    g.stub.makeBar("MainStatusTrackingBarContainer", 400, 20, 800, 10, True)
    g.G.SlashCmdList.XPORBS(f"shape {shape}")
    g.ns.SetLook(
        "density", 75
    )  # Quantity 75 % -> ShapePreview.Count = 6 (density is remembered per shape)
    opt = g.ns.Options
    opt.panel.scripts.OnShow(opt.panel)
    sp = g.ns.ShapePreview
    assert sp.window is not None and sp.window.shown, (
        "the preview window did not come up"
    )
    assert preview_area(g) is not None and int(preview_area(g).n) == 6
    return g


def make_shapes(out: Path):
    games = [shape_runtime(s, seed=5 + i) for i, (s, _) in enumerate(SHAPES)]
    readers = [Reader(g, preview_area(g)) for g in games]
    for g in (
        games
    ):  # the area is only populated by the first tick: warm up so frame 0 is not blank
        g.tick(SIM_DT, round(1.0 / SIM_DT))
    area_h = 0
    for (s, _), g in zip(SHAPES, games):
        area = preview_area(g)
        win = g.ns.ShapePreview.window
        h = int(win.height) - 36  # the window less its header row and bottom padding
        area_h = max(area_h, h)
        rested = sorted(int(k) for k in area.rested)
        print(
            f"shapes: {s}: n={int(area.n)} rested slots {rested} unit {float(area.unit):g} "
            f"window {int(win.width)}x{int(win.height)} (area {h} high)"
        )
    cell_w, cell_h = round(AREA_W * SHAPE_SCALE), round(area_h * SHAPE_SCALE)
    cols, rows = 2, 2
    gap, label_h = 10, 28
    plate_h = label_h + cell_h
    total_w, total_h = (
        cols * cell_w + (cols + 1) * gap,
        rows * plate_h + (rows + 1) * gap,
    )
    bg_full = night_background(total_w, total_h, seed=7, stars=26, noise=False)
    plate = Image.new("L", (total_w, total_h), 0)
    pd = ImageDraw.Draw(plate)

    def origin(i):
        return gap + (i % cols) * (cell_w + gap), gap + (i // cols) * (plate_h + gap)

    for i in range(4):
        x0, y0 = origin(i)
        pd.rounded_rectangle(
            [x0, y0, x0 + cell_w - 1, y0 + plate_h - 1], radius=8, fill=255
        )
    pm = (np.asarray(plate, dtype=np.float32) / 255.0)[..., None]
    bg_full = bg_full * (1 - 0.30 * pm)
    frames_n = round(LOOP * FPS)
    frames = []
    for _ in range(frames_n):
        canvas = bg_full.copy()
        for i, rd in enumerate(readers):
            x0, y0 = origin(i)
            region = np.ascontiguousarray(
                canvas[y0 + label_h : y0 + plate_h, x0 : x0 + cell_w]
            )
            composite(region, rd.read(), cell_w / 2, cell_h / 2, SHAPE_SCALE)
            canvas[y0 + label_h : y0 + plate_h, x0 : x0 + cell_w] = region
        img = to_pil(canvas)
        for i, (_, label) in enumerate(SHAPES):
            x0, y0 = origin(i)
            draw_label(img, label, x0 + cell_w // 2, y0 + 5)
        frames.append(img)
        for g in games:
            g.tick(SIM_DT, STEPS_PER_FRAME)
    to_gif(frames, out / "orb-shapes.gif", FPS)
    frames[0].save(out / "orb-shapes-frame00.png")
    frames[frames_n // 2].save(out / "orb-shapes-mid.png")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "what", nargs="?", default="all", choices=["flight", "shapes", "all"]
    )
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.what in ("flight", "all"):
        make_flight(out)
    if args.what in ("shapes", "all"):
        make_shapes(out)
    for p in sorted(out.glob("*.gif")):
        print(f"{p.name}: {p.stat().st_size:,} bytes")


if __name__ == "__main__":
    sys.exit(main())
