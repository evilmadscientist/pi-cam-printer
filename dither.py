"""Dither a photo to 1-bit black and white for a thermal printer.

Algorithm: Floyd-Steinberg error diffusion with serpentine scanning.

Why this one for photos of people: Floyd-Steinberg diffuses 100% of the
quantisation error, so it preserves the full tonal range of skin, shadows and
highlights. Atkinson (popular for thermal printers) discards 25% of the error,
which blows out faces and crushes shadows. Ordered/Bayer dithering produces a
visible cross-hatch pattern that looks harsh on faces. Serpentine scanning
(alternating row direction) removes the diagonal "worm" artifacts of plain
Floyd-Steinberg in smooth areas like cheeks and foreheads.

Thermal printers also suffer dot gain (printed dots bleed and look darker), so
the image is contrast-stretched, lightened with a gamma curve and sharpened
before dithering.
"""

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def preprocess(image, gamma=0.8, sharpen=True):
    """Prepare a photo for dithering: grayscale, autocontrast, gamma, sharpen."""
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    if sharpen:
        gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2))
    if gamma != 1.0:
        lut = [round(255 * (i / 255) ** gamma) for i in range(256)]
        gray = gray.point(lut)
    return gray


def floyd_steinberg(gray):
    """Serpentine Floyd-Steinberg dither of an 'L' image. Returns a mode '1' image."""
    # Plain Python lists are much faster than per-element numpy indexing here.
    pixels = np.asarray(gray, dtype=np.float32).tolist()
    h, w = len(pixels), len(pixels[0])
    for y in range(h):
        if y % 2 == 0:
            xs, step = range(w), 1
        else:
            xs, step = range(w - 1, -1, -1), -1
        row = pixels[y]
        next_row = pixels[y + 1] if y + 1 < h else None
        for x in xs:
            old = row[x]
            new = 255.0 if old >= 128 else 0.0
            row[x] = new
            err = old - new
            nx = x + step
            px = x - step
            if 0 <= nx < w:
                row[nx] += err * 7 / 16
            if next_row is not None:
                if 0 <= px < w:
                    next_row[px] += err * 3 / 16
                next_row[x] += err * 5 / 16
                if 0 <= nx < w:
                    next_row[nx] += err * 1 / 16
    return Image.fromarray(np.array(pixels, dtype=np.uint8)).convert("1", dither=Image.Dither.NONE)


def dither(image, gamma=0.8, sharpen=True):
    """Convert any PIL image to a 1-bit dithered PIL image (mode '1')."""
    return floyd_steinberg(preprocess(image, gamma=gamma, sharpen=sharpen))


if __name__ == "__main__":
    import sys

    dither(Image.open(sys.argv[1])).save(sys.argv[2])
