"""Convert a 1-bit image to the thermal printer bitmap format and a HEX file.

Format (same as Adafruit's Thermal Printer bitmap tools): each row is packed
into ceil(width / 8) bytes, most significant bit = leftmost pixel, and a set
bit (1) means a black dot. Rows are stored top to bottom.
"""

import os

import numpy as np
from PIL import Image


def image_to_bitmap(image):
    """Pack a PIL image into printer bitmap bytes.

    Returns ``(data, width, height)`` where ``width`` is the pixel width.
    """
    bw = image.convert("1")
    pixels = np.asarray(bw, dtype=bool)  # True = white in PIL mode '1'
    black = ~pixels
    data = np.packbits(black, axis=1)  # pads each row to a whole byte with 0 (white)
    return data.tobytes(), bw.width, bw.height


def write_hex_file(data, width, height, path, name=None):
    """Write bitmap bytes as a C header, like Adafruit's bitmapImageConvert tool."""
    name = name or os.path.splitext(os.path.basename(path))[0]
    row_bytes = (width + 7) // 8
    lines = [
        f"#ifndef _{name}_h_",
        f"#define _{name}_h_",
        "",
        f"#define {name}_width  {width}",
        f"#define {name}_height {height}",
        "",
        f"static const uint8_t PROGMEM {name}_data[] = {{",
    ]
    for y in range(height):
        row = data[y * row_bytes:(y + 1) * row_bytes]
        lines.append("  " + ",".join(f"0x{b:02X}" for b in row) + ",")
    lines += ["};", "", "#endif", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))


def convert_image(image, hex_path=None):
    """Convert a 1-bit PIL image to bitmap bytes, optionally saving a HEX file."""
    data, width, height = image_to_bitmap(image)
    if hex_path:
        write_hex_file(data, width, height, hex_path)
    return data, width, height


if __name__ == "__main__":
    import sys

    d, w, h = convert_image(Image.open(sys.argv[1]), sys.argv[2])
    print(f"Wrote {sys.argv[2]}: {w}x{h}, {len(d)} bytes")
