"""Build media/icon.tga (addon list, minimap button, addon compartment) from docs/images/icon.png.

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


def main() -> None:
    art = erase_text(Image.open(SRC).convert("RGB"))
    if "--purple" in sys.argv[1:]:
        art = purple(art)
    out = art.crop(CROP).resize((SIZE, SIZE), Image.Resampling.LANCZOS).convert("RGBA")
    out.save(OUT, format="TGA", compression=None)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
