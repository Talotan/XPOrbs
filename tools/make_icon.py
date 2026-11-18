"""Build the small icons from docs/images/icon.png.

Run: uv run --with pillow --with numpy python tools/make_icon.py [--purple]
Writes 64x64 uncompressed 32-bit TGAs (bottom-left origin), like tools/make_textures.py:
- media/icon.tga          addon list + addon compartment (toc IconTexture): cropped 1.19x so "XP" reads at 16-20 px
- media/icon-minimap.tga  LibDBIcon button: uncropped, so the letters stay inside the gold ring
Both thicken and brighten the gold "XP" first; at 18 px the original hairlines average into the outline.
--purple rotates the blue orbs to the normal-orb purple (hue ~278 deg) and leaves the navy and the gold alone.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "images" / "icon.png"
MEDIA = ROOT / "media"
SIZE = 64
LIST_CROP = (40, 44, 472, 476)  # the art's spare margin; too tight for the minimap ring


def gold_mask(im):
    """Mask of the gold lettering (Pillow HSV hue 14-48 of 255), closed to remove speckle."""
    h, s, v = np.asarray(im.convert("HSV")).astype(int).transpose(2, 0, 1)
    m = (h >= 14) & (h <= 48) & (s >= 90) & (v >= 70)
    mask = Image.fromarray((m * 255).astype(np.uint8))
    return mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))


def bold_gold(im, grow=5, stroke=6, gain=1.3):
    """Faux-bold the gold letters, keep a dark outline round them, and brighten them without shifting hue."""
    m = gold_mask(im)
    k = 2 * grow + 1
    gold = Image.composite(im, Image.new("RGB", im.size), m).filter(
        ImageFilter.MaxFilter(k)
    )
    m_big = m.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.GaussianBlur(1.2))
    m_stroke = m.filter(ImageFilter.MaxFilter(k + 2 * stroke)).filter(
        ImageFilter.GaussianBlur(1.5)
    )
    out = Image.composite(Image.new("RGB", im.size, (6, 5, 10)), im, m_stroke)
    out = Image.composite(gold, out, m_big)
    a = np.asarray(out).astype(float)
    mb = np.asarray(m_big)[..., None] / 255
    scale = np.minimum(255 / a.max(-1, keepdims=True).clip(1), gain)
    return Image.fromarray(
        (a * (1 - mb) + np.clip(a * scale, 0, 255) * mb).astype(np.uint8)
    )


def purple(im):
    """Rotate the blue orb hues to ~278 deg; the dark navy background and the gold stay as they are."""
    hsv = np.asarray(im.convert("HSV")).astype(float)
    h = hsv[..., 0]
    blue = (h > 130) & (h < 190)
    w = np.clip((hsv[..., 2] - 40) / 80, 0, 1) * blue
    hsv[..., 0] = h * (1 - w) + (278 / 360 * 255) * w
    return Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")


def to64(im):
    out = im.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    return out.filter(
        ImageFilter.UnsharpMask(radius=1.0, percent=70, threshold=0)
    ).convert("RGBA")


def save(img, name):
    path = MEDIA / name
    img.save(path, format="TGA", compression=None)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def main() -> None:
    art = bold_gold(Image.open(SRC).convert("RGB"))
    if "--purple" in sys.argv[1:]:
        art = purple(art)
    save(to64(art.crop(LIST_CROP)), "icon.tga")
    save(to64(art), "icon-minimap.tga")


if __name__ == "__main__":
    main()
