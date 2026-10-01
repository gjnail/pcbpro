"""The site's icons and the link-preview pictures, from the app icon and the 3D renders in docs/media.

    python tools/docs_media/make_brand.py

Writes docs/media/img/icon-256.png, icon-64.png, og.jpg (1200 x 630, the website's link preview) and
social-preview.png (1280 x 640, for the GitHub repository's Settings > Social preview, which can only be uploaded
by hand). Run capture.py and encode_media.py first: it uses their 3D renders. Needs Pillow; on Windows it uses the
system's Bahnschrift and Segoe UI fonts, elsewhere Pillow's default font.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "docs" / "media" / "img"
EXAMPLES = ROOT / "docs" / "media" / "examples"
BG = (11, 13, 16)
ACCENT = (238, 162, 58)
GREEN = (63, 207, 142)
TEXT = (233, 235, 238)
MUTED = (163, 169, 179)


def font(names: list[str], size: int):
    for n in names:
        for d in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts")):
            p = d / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def icon() -> Image.Image:
    ico = Image.open(ROOT / "pcbpro" / "resources" / "pcbpro.ico")
    ico.size = max(ico.ico.sizes())
    return ico.convert("RGBA")


def backdrop(w: int, h: int) -> Image.Image:
    """Dark background with a soft copper glow at the top left and a green one at the right."""
    img = Image.new("RGB", (w, h), BG)
    glow = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(glow)
    d.ellipse((-w * 0.25, -h * 0.6, w * 0.55, h * 0.7), fill=(58, 40, 18))
    d.ellipse((w * 0.55, -h * 0.2, w * 1.3, h * 1.1), fill=(16, 44, 34))
    return Image.blend(img, glow.filter(ImageFilter.GaussianBlur(min(w, h) // 5)), 0.9)


def render(name: str) -> Image.Image:
    return Image.open(EXAMPLES / f"{name}.webp").convert("RGB")


def card(w: int, h: int) -> Image.Image:
    img = backdrop(w, h)
    s = h / 640
    # two 3D renders on the right: the pedal in its box, and a tube amp
    for name, box in (("Amp_Plexi_Crunch_50W", (0.40, 0.42, 1.04, 1.02)),
                      ("Three_Knob_Overdrive_125B-box", (0.50, -0.06, 1.02, 0.62))):
        r = render(name)
        x0, y0, x1, y1 = int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)
        r = r.resize((x1 - x0, round((x1 - x0) * r.height / r.width)), Image.LANCZOS)
        # fade the render's own dark background into ours
        lum = r.convert("L").point(lambda v: 0 if v < 30 else min(255, (v - 30) * 6))
        img.paste(r, (x0, y0), lum.filter(ImageFilter.GaussianBlur(2)))
    # a scrim behind the text so it reads over the renders
    scrim = Image.new("L", (w, h), 0)
    ImageDraw.Draw(scrim).rectangle((0, 0, int(w * 0.58), h), fill=200)
    scrim = scrim.filter(ImageFilter.GaussianBlur(int(60 * s)))
    img.paste(Image.new("RGB", (w, h), BG), (0, 0), scrim)
    d = ImageDraw.Draw(img)
    ic = icon().resize((int(112 * s), int(112 * s)), Image.LANCZOS)
    img.paste(ic, (int(70 * s), int(92 * s)), ic)
    title = font(["bahnschrift.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"], int(96 * s))
    body = font(["segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"], int(34 * s))
    small = font(["segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"], int(24 * s))
    d.text((int(70 * s), int(222 * s)), "PCBPro", font=title, fill=TEXT)
    lines = ["PCB design for guitar pedals,", "tube amps and everything else"]
    for i, line in enumerate(lines):
        d.text((int(72 * s), int(344 * s + i * 46 * s)), line, font=body, fill=MUTED)
    tags = ["LAYOUT", "3D", "SIMULATE", "PLAY", "ORDER"]
    x = int(72 * s)
    for i, t in enumerate(tags):
        colour = ACCENT if i % 2 == 0 else GREEN
        d.text((x, int(470 * s)), t, font=small, fill=colour)
        x += int(d.textlength(t, font=small) + 26 * s)
    d.text((int(72 * s), int(560 * s)), "github.com/gjnail/pcbpro  ·  free and open source (MIT)",
           font=font(["segoeui.ttf", "DejaVuSans.ttf"], int(22 * s)), fill=(114, 121, 133))
    return img


def main() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    ic = icon()
    ic.resize((256, 256), Image.LANCZOS).save(IMG / "icon-256.png")
    ic.resize((64, 64), Image.LANCZOS).save(IMG / "icon-64.png")
    card(1200, 630).save(IMG / "og.jpg", quality=88)
    card(1280, 640).save(IMG / "social-preview.png", optimize=True)
    for n in ("icon-256.png", "icon-64.png", "og.jpg", "social-preview.png"):
        print(n, f"{(IMG / n).stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    sys.exit(main())
