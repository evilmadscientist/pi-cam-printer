"""Resize an image to a target height while keeping its aspect ratio."""

from PIL import Image

DEFAULT_HEIGHT = 384


def downscale(image, height=DEFAULT_HEIGHT):
    """Return a copy of ``image`` scaled to ``height`` pixels tall.

    The width is scaled proportionally. Lanczos resampling keeps fine detail
    (eyes, hair) crisp, which matters once the image is dithered to 1 bit.
    """
    if height <= 0:
        raise ValueError("height must be positive")
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    import sys

    src, dst = sys.argv[1], sys.argv[2]
    h = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_HEIGHT
    downscale(Image.open(src), h).save(dst)
