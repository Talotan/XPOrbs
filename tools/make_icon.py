"""Build media/icon.tga (minimap button) and media/icon-list.tga (AddOns list, compartment) from docs/images/icon.png.

icon.tga is borderless (LibDBIcon draws its own round ring). icon-list.tga is the same art filling a square with a baked
gold rounded-square frame with a dark inner line and navy fill (like the neighbouring list icons),
because the AddOns list draws the toc IconTexture with no frame of its own.

Run: uv run --with pillow --with numpy python tools/make_icon.py [--purple]
The gold "XP" is erased (the name is printed next to the icon everywhere it shows, and at 16-20 px the letters
smear), then the comet is cropped so it sits centred. Writes a 64x64 uncompressed 32-bit TGA (bottom-left origin),
like tools/make_textures.py. --purple rotates the blue orbs to the normal-orb purple (hue ~278 deg).
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "images" / "icon.png"
OUT = ROOT / "media" / "icon.tga"
OUT_LIST = ROOT / "media" / "icon-list.tga"
SIZE = 64
CROP = (
    60,
    0,
    420,
    360,
)  # centres the comet once the text is gone; stays inside LibDBIcon's button ring


def gold_mask(im):
    """Mask of the gold lettering (Pillow HSV hue 14-48 of 255)."""
    h, s, v = np.asarray(im.convert("HSV")).astype(int).transpose(2, 0, 1)
    m = (h >= 14) & (h <= 48) & (s >= 90) & (v >= 70)
    return Image.fromarray((m * 255).astype(np.uint8))


def erase_text(im):
    """Replace the whole text block (letters, outline, shadow) with the background gradient.

    Each row is filled by blending between clean columns either side of the text, so the navy gradient carries
    through without dragging the orb's glow down into the gap.
    """
    bbox = gold_mask(im).getbbox()
    if bbox is None:
        return im  # no text in the source art
    x0, y0, x1, y1 = bbox
    box = Image.new("L", im.size, 0)
    ImageDraw.Draw(box).rectangle(
        (x0 - 40, y0 - 30, x1 + 40, min(im.height - 1, y1 + 40)), fill=255
    )
    keep = (
        1 - np.asarray(box.filter(ImageFilter.GaussianBlur(14)), float)[..., None] / 255
    )
    a = np.asarray(im, float)
    xl, xr = x0 - 55, x1 + 55
    left = a[:, xl - 5 : xl, :].mean(1, keepdims=True)
    right = a[:, xr : xr + 5, :].mean(1, keepdims=True)
    t = np.clip((np.arange(im.width)[None, :, None] - xl) / (xr - xl), 0, 1)
    fill = np.clip(left * (1 - t) + right * t, 0, 255).astype(np.uint8)
    fill = np.asarray(Image.fromarray(fill).filter(ImageFilter.GaussianBlur(3)), float)
    return Image.fromarray(
        np.clip(a * keep + fill * (1 - keep), 0, 255).astype(np.uint8)
    )


def purple(im):
    """Rotate the blue orb hues to ~278 deg; the dark navy background stays as it is."""
    hsv = np.asarray(im.convert("HSV")).astype(float)
    h = hsv[..., 0]
    w = np.clip((hsv[..., 2] - 40) / 80, 0, 1) * ((h > 130) & (h < 190))
    hsv[..., 0] = h * (1 - w) + (278 / 360 * 255) * w
    return Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")


def _lerp_stops(t, stops):
    """Piecewise-linear colour ramp: stops is [(t, (r, g, b)), ...]; t is an array in 0..1."""
    xs = [s[0] for s in stops]
    return np.stack([np.interp(t, xs, [s[1][c] for s in stops]) for c in range(3)], -1)


def tone_comet(art_arr):
    """Pull the comet down so it sits with its neighbours: smaller halo, core capped well below white.

    Subtracts the art's own navy, darkens the halo with a gamma, then soft-knees each channel to a per-channel
    ceiling (core ~ 188/208/214, a pale blue rather than white-hot).
    """
    glow = np.clip(art_arr - np.array([10.0, 15.0, 36.0]), 0, None) / 245.0
    glow = glow**1.45
    cap = np.array([188.0, 208.0, 214.0])
    knee = 0.62  # fraction of the cap where compression starts
    v = glow * 255.0
    lo = cap * knee
    over = np.clip((v - lo) / (cap - lo), 0, None)
    v = np.where(v > lo, lo + (cap - lo) * np.tanh(over) * 1.0, v)
    return np.minimum(v, cap)


def frame(art):
    """Square art in a baked gold rounded-square frame, to match the neighbouring AddOns-list icons.

    Geometry is in 64 px texture units, chosen so the ~20 px list display gets a ~1.6 px gold frame running
    straight into the navy fill (no dark line) and a 2.5 px corner radius (x3.2 each). Rendered at 8x with an analytic
    rounded-rect distance field and box-downscaled, so the corners are cleanly antialiased and transparent outside.
    """
    k = 8
    n = SIZE * k
    gold_w, line_w, radius = 5.2 * k, 0.0, 8 * k
    ys, xs = (np.mgrid[0:n, 0:n] + 0.5)
    half = n / 2
    qx, qy = np.abs(xs - half) - (half - radius), np.abs(ys - half) - (half - radius)
    dist_out = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - radius
    depth = -dist_out  # distance in from the edge
    # gold sampled from the neighbouring icons' frames: lit top-left, shaded bottom-right
    t = 0.3 * xs / n + 0.7 * ys / n
    gold = _lerp_stops(
        t,
        [(0, (240, 221, 164)), (0.15, (214, 196, 140)), (0.35, (170, 148, 100)), (0.6, (192, 136, 34)),
         (1, (178, 124, 24))],
    )
    # dark navy fill (neighbours: ~#1e2438 at the top down to ~#0f121d), then the toned-down comet on it
    v = np.clip((ys - gold_w - line_w) / (n - 2 * (gold_w + line_w)), 0, 1)[..., None]
    navy = np.array([33.0, 39.0, 62.0]) * (1 - v) + np.array([13.0, 16.0, 28.0]) * v
    inner = (n - 2 * gold_w - 2 * line_w) / n
    w0, h0 = art.size
    art = art.crop((w0 // 12, h0 // 12, w0 - w0 // 12, h0 - h0 // 12))  # ~1.2x zoom: the comet reads bigger at 20 px
    a = np.asarray(art.resize((n, n), Image.Resampling.LANCZOS).convert("RGB"), float)
    # shrink the art onto the interior only, so the comet stays clear of the frame
    sh = round(n * inner)
    off = (n - sh) // 2
    sub = np.asarray(Image.fromarray(a.astype(np.uint8)).resize((sh, sh), Image.Resampling.LANCZOS), float)
    comet = np.zeros_like(a)
    comet[off : off + sh, off : off + sh] = tone_comet(sub)
    fill = np.minimum(navy + comet, np.array([196.0, 208.0, 214.0]))  # hard cap: nothing outshines the neighbours
    line = np.array([26.0, 25.0, 30.0]) * (1 - t[..., None]) + np.array([10.0, 11.0, 17.0]) * t[..., None]
    out = np.where((depth >= gold_w + line_w)[..., None], fill, np.where((depth >= gold_w)[..., None], line, gold))
    alpha = np.clip(depth + 0.5, 0, 1) * 255.0  # 1 sample of AA at 8x; the box downscale does the rest
    rgb = out * (alpha[..., None] / 255.0)  # premultiplied so the box filter cannot leak dark fringes
    rgb = rgb.reshape(SIZE, k, SIZE, k, 3).mean((1, 3))
    al = alpha.reshape(SIZE, k, SIZE, k).mean((1, 3))
    rgb = np.where(al[..., None] > 0, rgb / np.maximum(al[..., None], 1e-6) * 255.0, 0)
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), al]).round().astype(np.uint8), "RGBA")


def main() -> None:
    art = erase_text(Image.open(SRC).convert("RGB"))
    if "--purple" in sys.argv[1:]:
        art = purple(art)
    out = art.crop(CROP).resize((SIZE, SIZE), Image.Resampling.LANCZOS).convert("RGBA")
    out.save(OUT, format="TGA", compression=None)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    framed = frame(art.crop(CROP))
    framed.save(OUT_LIST, format="TGA", compression=None)
    print(f"wrote {OUT_LIST.relative_to(ROOT)} ({OUT_LIST.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
