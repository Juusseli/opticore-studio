"""Draw the application icon (as frontend/public/favicon.svg) into packaging/assets: a Windows .ico and a 256 px PNG.

Run with the engine's Python (Pillow is installed with it): python packaging/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "assets"


def icon(size: int) -> Image.Image:
    """The favicon drawn at 4x and reduced: a rounded square with a sky-to-indigo gradient, rays and a lens."""
    s = size * 4
    k = s / 64  # the SVG's 64-unit grid
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s))
    g = ImageDraw.Draw(grad)
    a, b = (0x38, 0xBD, 0xF8), (0x63, 0x66, 0xF1)
    for i in range(2 * s):  # diagonal gradient, top left to bottom right
        t = min(1.0, i / (2 * s - 1))
        g.line([(i, 0), (0, i)], fill=tuple(int(a[j] + (b[j] - a[j]) * t) for j in range(3)) + (255,), width=2)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=14 * k, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w = max(1, round(3.5 * k))
    for p, q in (((14, 22), (32, 32)), ((32, 32), (50, 22)), ((14, 42), (32, 32)), ((32, 32), (50, 42))):
        d.line([(p[0] * k, p[1] * k), (q[0] * k, q[1] * k)], fill="white", width=w)
    d.ellipse([27 * k, 17 * k, 37 * k, 47 * k], outline="white", width=max(1, round(3 * k)))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = icon(256)
    big.save(OUT / "opticore-studio.png")
    big.save(OUT / "opticore-studio.ico", sizes=[(n, n) for n in sizes], append_images=[icon(n) for n in sizes[:-1]])
    print("icons written to", OUT)
