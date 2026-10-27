"""Resize an image to a target height while keeping its aspect ratio."""

import os

from PIL import Image

DEFAULT_HEIGHT = 384


def _open(image):
    """Accept a PIL image or a path to an image file (JPEG, PNG, ...)."""
    if isinstance(image, (str, os.PathLike)):
        with Image.open(image) as f:
            return f.convert("RGB")
    return image


def downscale(image, height=DEFAULT_HEIGHT):
    """Return a copy of ``image`` scaled to ``height`` pixels tall.

    ``image`` may be a PIL image or a path to an image file (JPEG, PNG).
    The width is scaled proportionally. Lanczos resampling keeps fine detail
    (eyes, hair) crisp, which matters once the image is dithered to 1 bit.
    """
    if height <= 0:
        raise ValueError("height must be positive")
    image = _open(image)
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    import sys

    src, dst = sys.argv[1], sys.argv[2]
    h = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_HEIGHT
    downscale(src, h).save(dst)
