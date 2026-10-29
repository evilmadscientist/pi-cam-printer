"""Send a rendered bitmap to a Teensy 3.2 over USB serial, which prints it on
the thermal printer (see print_serial_image/print_serial_image.ino).

The Teensy drives the printer from its hardware UART with DTR handshaking, so
the printer itself paces the data and nothing here needs delays or chunking.

Protocol (multi-byte values are little-endian):

    Pi     -> Teensy   b"IMG1" + width:u16 + height:u16 + feed_lines:u8
    Teensy -> Pi       "READY"                  (or "ERR <reason>")
    Pi     -> Teensy   ceil(width / 8) * height bitmap bytes
                       (MSB = leftmost dot, 1 = black)
    Pi     -> Teensy   b"DONE" + checksum:u32   transfer-complete ack;
                       checksum = sum of the bitmap bytes mod 2**32
    Teensy -> Pi       "OK"                     (or "ERR <reason>"), then prints
    Teensy -> Pi       "PRINTED"                once everything is sent to the printer

Replies are newline-terminated. Lines from the Teensy starting with "#" are
debug output and are echoed here.
"""

import struct
import time

import serial

PRINTER_WIDTH_DOTS = 384
MAX_ROW_BYTES = PRINTER_WIDTH_DOTS // 8  # 48
DEFAULT_PORT = "/dev/ttyACM0"

MAGIC = b"IMG1"
DONE = b"DONE"


class TeensyError(RuntimeError):
    """The Teensy reported an error, or didn't answer in time."""


def _clip_rows(data, width, height):
    """Clip rows wider than the print head, so the Teensy's buffer only holds
    what can actually be printed."""
    row_bytes = (width + 7) // 8
    if row_bytes <= MAX_ROW_BYTES:
        return bytes(data), width
    clipped = b"".join(data[y * row_bytes:y * row_bytes + MAX_ROW_BYTES] for y in range(height))
    return clipped, PRINTER_WIDTH_DOTS


def _expect(ser, token, timeout):
    """Wait for the reply line ``token`` from the Teensy."""
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        buf += ser.readline()
        if not buf.endswith(b"\n"):
            continue  # read timed out mid-line; keep accumulating
        line = buf.decode("ascii", errors="replace").strip()
        buf = b""
        if not line:
            continue
        if line.startswith("#"):
            print(f"[teensy] {line[1:].strip()}")
        elif line == token:
            return
        elif line.startswith("ERR"):
            raise TeensyError(f"Teensy reported: {line}")
        else:
            raise TeensyError(f"unexpected reply from Teensy: {line!r} (wanted {token!r})")
    raise TeensyError(f"timed out after {timeout}s waiting for {token!r} from the Teensy")


def print_image(data, width, height, port=DEFAULT_PORT, feed_lines=3, print_timeout=120.0):
    """Send a packed 1-bit bitmap to the Teensy and wait until it's printed."""
    if not 0 <= feed_lines <= 255:
        raise ValueError("feed_lines must be 0-255")
    data, width = _clip_rows(data, width, height)
    checksum = sum(data) & 0xFFFFFFFF

    # The baud rate is ignored by the Teensy's native USB serial.
    with serial.Serial(port, 115200, timeout=0.5, write_timeout=10) as ser:
        ser.reset_input_buffer()
        ser.write(MAGIC + struct.pack("<HHB", width, height, feed_lines))
        try:
            _expect(ser, "READY", timeout=5)
        except TeensyError as e:
            if "timed out" in str(e):
                raise TeensyError(
                    f"{e}. Is print_serial_image.ino flashed and running on {port}? "
                    "A stuck setup() (e.g. waiting on the printer) looks the same."
                ) from None
            raise

        ser.write(data)
        ser.write(DONE + struct.pack("<I", checksum))
        _expect(ser, "OK", timeout=10)

        # Printing a full photo takes a while; the printer sets the pace via DTR.
        _expect(ser, "PRINTED", timeout=print_timeout)


if __name__ == "__main__":
    import sys

    from PIL import Image

    from convert_image import convert_image

    port = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PORT
    print_image(*convert_image(Image.open(sys.argv[1])), port=port)
