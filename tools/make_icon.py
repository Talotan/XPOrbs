"""Build media/icon.tga (minimap button) and media/icon-list.tga (AddOns list, compartment) from docs/images/icon.png.

icon.tga is borderless (LibDBIcon draws its own round ring). icon-list.tga is the same art filling a square with a baked
spell-icon style frame (1 px dark outline, 3 px bevel lit from the top-left, 1 px inner shade, rounded corners),
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


def frame(art):
    """Square art with a baked bevelled spell-icon border; built at 4x and downscaled for smooth corners."""
    k = 4
    n = SIZE * k
    a = np.asarray(art.resize((n, n), Image.Resampling.LANCZOS).convert("RGB"), float)
    ys, xs = np.mgrid[0:n, 0:n]
    dx, dy = np.minimum(xs, n - 1 - xs), np.minimum(ys, n - 1 - ys)
    depth = np.minimum(dx, dy)
    lit = ((dx <= dy) & (xs < n // 2)) | ((dy < dx) & (ys < n // 2))  # left or top edge
    mid = (xs >= n // 2) != (ys >= n // 2)  # top-right / bottom-left corners blend
    light, dark, shade = np.array([212, 196, 150.0]), np.array([74, 66, 48.0]), np.array([20, 18, 16.0])
    bevel = np.where(lit[..., None], light, dark)
    bevel = np.where((mid & (np.abs(dx - dy) < 3 * k))[..., None], (light + dark) / 2, bevel)
    outer = np.array([6, 6, 8.0])
    out = a.copy()
    out = np.where((depth >= 4 * k)[..., None] & (depth < 5 * k)[..., None], a * 0.45 + shade * 0.55, out)
    out = np.where((depth < 4 * k)[..., None], bevel, out)
    out = np.where((depth < 1 * k)[..., None], outer, out)
    r = 5 * k  # corner radius
    cx, cy = np.clip(xs, r, n - 1 - r), np.clip(ys, r, n - 1 - r)
    alpha = ((xs - cx) ** 2 + (ys - cy) ** 2 <= r * r) * 255.0
    rgba = np.dstack([out, alpha]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA").resize((SIZE, SIZE), Image.Resampling.BOX)


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
