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

    def print_bitmap(self, data, width, height):
        """Print packed bitmap rows (MSB = leftmost dot, 1 = black).

        Rows wider than the 384-dot print head are clipped on the right.
        """
        row_bytes = (width + 7) // 8
        row_bytes_clipped = min(row_bytes, MAX_ROW_BYTES)
        # Send small chunks and pace them so the printer's buffer never overflows
        # (it has no flow control on the TX-only wiring).
        chunk_rows = 16
        for row_start in range(0, height, chunk_rows):
            rows = min(chunk_rows, height - row_start, MAX_CHUNK_ROWS)
            self._write(DC2, ord("*"), rows, row_bytes_clipped)
            chunk = bytearray()
            for y in range(row_start, row_start + rows):
                offset = y * row_bytes
                chunk += data[offset:offset + row_bytes_clipped]
            self._serial.write(chunk)
            self._serial.flush()
            time.sleep(rows * self._dot_print_time)

    def feed(self, lines=1):
        self._write(ESC, ord("d"), lines)
        time.sleep(lines * 0.05)

    def close(self):
        self._serial.close()


def print_image(data, width, height, port="/dev/serial0", baudrate=19200, feed_lines=3):
    """One-shot helper: open the printer, print a bitmap, feed paper, close."""
    printer = ThermalPrinter(port=port, baudrate=baudrate)
    try:
        printer.print_bitmap(data, width, height)
        printer.feed(feed_lines)
    finally:
        printer.close()


if __name__ == "__main__":
    import sys

    from PIL import Image

    from convert_image import convert_image

    print_image(*convert_image(Image.open(sys.argv[1])))
