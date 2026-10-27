"""Print a bitmap on an Adafruit Mini Thermal Receipt Printer over serial.

Connection follows Adafruit's CircuitPython / Raspberry Pi guide: printer RX
to the Pi's TX (GPIO 14), printer GND to Pi GND, using ``/dev/serial0`` at the
printer's baud rate (19200 for most units; printed on the self-test page).

The adafruit_thermal_printer library has no bitmap support, so this module
sends the same ESC/POS commands the Adafruit Arduino library uses for
``printBitmap()``: ``DC2 '*' rows rowBytes`` followed by the row data.
"""

import time

import serial

PRINTER_WIDTH_DOTS = 384
MAX_ROW_BYTES = PRINTER_WIDTH_DOTS // 8  # 48
MAX_CHUNK_ROWS = 255

ESC = 0x1B
DC2 = 0x12


class ThermalPrinter:
    def __init__(
        self,
        port="/dev/serial0",
        baudrate=19200,
        heat_dots=11,
        heat_time=120,
        heat_interval=40,
        dot_print_time=0.03,
    ):
        """Open the serial port and initialise the printer.

        heat_time: higher = darker but slower (3-255). heat_interval: higher =
        darker but slower. heat_dots: max dots heated at once (units of 8 dots).
        dot_print_time: seconds to allow per printed dot row.
        """
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=3)
        self._dot_print_time = dot_print_time
        time.sleep(0.5)  # printer needs a moment after power-up
        self._write(ESC, ord("@"))  # reset
        self._write(ESC, ord("7"), heat_dots, heat_time, heat_interval)
        # Print density / break time (same as Adafruit library defaults).
        self._write(DC2, ord("#"), (4 << 5) | 10)

    def _write(self, *data):
        self._serial.write(bytes(data))
        self._serial.flush()

    def print_bitmap(self, data, width, height, num_segments=8, segment_delay=2.0):
        """Print packed bitmap rows (MSB = leftmost dot, 1 = black).

        Rows wider than the 384-dot print head are clipped on the right.

        The image is split into ``num_segments`` vertical segments (top to
        bottom), printed one after another with a ``segment_delay`` second
        pause in between. The printer has no flow control on its TX-only
        wiring, so sending a large image as one burst can overrun its
        receive buffer and corrupt the print; pausing between segments gives
        it time to catch up.
        """
        row_bytes = (width + 7) // 8
        row_bytes_clipped = min(row_bytes, MAX_ROW_BYTES)
        # Within a segment, also send small chunks paced by dot_print_time so
        # the buffer fills gradually rather than all at once.
        chunk_rows = 16

        num_segments = max(1, num_segments)
        segment_height = max(1, -(-height // num_segments))  # ceil(height / num_segments)
        segment_starts = list(range(0, height, segment_height)) or [0]

        for i, seg_start in enumerate(segment_starts):
            seg_end = min(seg_start + segment_height, height)
            for row_start in range(seg_start, seg_end, chunk_rows):
                rows = min(chunk_rows, seg_end - row_start, MAX_CHUNK_ROWS)
                self._write(DC2, ord("*"), rows, row_bytes_clipped)
                chunk = bytearray()
                for y in range(row_start, row_start + rows):
                    offset = y * row_bytes
                    chunk += data[offset:offset + row_bytes_clipped]
                self._serial.write(chunk)
                self._serial.flush()
                time.sleep(rows * self._dot_print_time)
            if i < len(segment_starts) - 1:
                time.sleep(segment_delay)

    def feed(self, lines=1):
        self._write(ESC, ord("d"), lines)
        time.sleep(lines * 0.05)

    def close(self):
        self._serial.close()


def print_image(
    data,
    width,
    height,
    port="/dev/serial0",
    baudrate=19200,
    feed_lines=3,
    num_segments=8,
    segment_delay=1.0,
):
    """One-shot helper: open the printer, print a bitmap, feed paper, close."""
    printer = ThermalPrinter(port=port, baudrate=baudrate)
    try:
        printer.print_bitmap(data, width, height, num_segments=num_segments, segment_delay=segment_delay)
        printer.feed(feed_lines)
    finally:
        printer.close()


if __name__ == "__main__":
    import sys

    from PIL import Image

    from convert_image import convert_image

    print_image(*convert_image(Image.open(sys.argv[1])))
