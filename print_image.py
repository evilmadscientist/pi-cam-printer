"""Print a bitmap on an Adafruit Mini Thermal Receipt Printer over serial.

Connection follows Adafruit's CircuitPython / Raspberry Pi guide: printer RX
to the Pi's TX (GPIO 14), printer GND to Pi GND, using ``/dev/serial0`` at the
printer's baud rate (19200 for most units; printed on the self-test page).

The adafruit_thermal_printer library has no bitmap support, so this module
sends the same ESC/POS commands the Adafruit Arduino library uses for
``printBitmap()``: ``DC2 '*' rows rowBytes`` followed by the row data.

Flow control: this printer model also exposes a DTR (Data Terminal Ready)
wire. Wire it to a Pi GPIO input and the printer will pull it LOW when it's
ready for more data and hold it HIGH while busy -- the same handshake the
Adafruit Arduino library uses (``GS 'a' n`` enables it; see their
``Adafruit_Thermal::begin()``). This is more reliable than guessing fixed
delays from the baud rate, since it reflects what the printer is actually
doing. Pass ``dtr_pin=None`` to fall back to fixed-delay pacing if the wire
isn't connected.
"""

import time

import serial

try:
    from gpiozero import DigitalInputDevice
except ImportError:  # not installed / not running on a Pi
    DigitalInputDevice = None

PRINTER_WIDTH_DOTS = 384
MAX_ROW_BYTES = PRINTER_WIDTH_DOTS // 8  # 48
MAX_CHUNK_ROWS = 255
DTR_PIN = 23

ESC = 0x1B
DC2 = 0x12
GS = 0x1D


class ThermalPrinter:
    def __init__(
        self,
        port="/dev/serial0",
        baudrate=19200,
        heat_dots=11,
        heat_time=120,
        heat_interval=40,
        dot_print_time=0.03,
        dtr_pin=DTR_PIN,
        dtr_timeout=5.0,
    ):
        """Open the serial port and initialise the printer.

        heat_time: higher = darker but slower (3-255). heat_interval: higher =
        darker but slower. heat_dots: max dots heated at once (units of 8 dots).
        dot_print_time: seconds to allow per printed dot row; only used as a
        fallback when ``dtr_pin`` is None.
        dtr_pin: BCM GPIO pin wired to the printer's DTR line, used for flow
        control instead of fixed delays. Pass None to disable and fall back
        to timed pacing.
        dtr_timeout: max seconds to wait on the DTR line before giving up and
        continuing anyway, in case it's wired wrong or disconnected.
        """
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=3)
        self._dot_print_time = dot_print_time
        self._dtr_timeout = dtr_timeout
        time.sleep(0.5)  # printer needs a moment after power-up
        self._write(ESC, ord("@"))  # reset
        self._write(ESC, ord("7"), heat_dots, heat_time, heat_interval)
        # Print density / break time (same as Adafruit library defaults).
        self._write(DC2, ord("#"), (4 << 5) | 10)

        self._dtr = None
        if dtr_pin is not None:
            if DigitalInputDevice is None:
                raise RuntimeError(
                    "gpiozero is required for DTR flow control (pip install gpiozero), "
                    "or pass dtr_pin=None to use fixed-delay pacing instead"
                )
            # Tell the printer to start driving its DTR pin (same command the
            # Adafruit Arduino library sends in Adafruit_Thermal::begin()).
            self._write(GS, ord("a"), 1 << 5)
            # Idle/busy = HIGH, ready = LOW, so with pull_up=True "active" (pin
            # LOW) means "ready for more data" -- matching the printer's signal.
            self._dtr = DigitalInputDevice(dtr_pin, pull_up=True)

    def _write(self, *data):
        self._serial.write(bytes(data))
        self._serial.flush()

    def _wait_ready(self):
        """Block until the printer's DTR line says it can accept more data."""
        if self._dtr is not None:
            self._dtr.wait_for_active(timeout=self._dtr_timeout)

    def print_bitmap(self, data, width, height, num_segments=1, segment_delay=1.0):
        """Print packed bitmap rows (MSB = leftmost dot, 1 = black).

        Rows wider than the 384-dot print head are clipped on the right.

        The image is split into ``num_segments`` vertical segments (top to
        bottom), printed one after another with a ``segment_delay`` second
        pause in between. This is mainly a fallback for when DTR flow control
        (see the class docstring) isn't wired up: without it, the printer has
        no way to tell the host it's busy, so sending a large image as one
        burst can overrun its receive buffer and corrupt the print.
        """
        row_bytes = (width + 7) // 8
        row_bytes_clipped = min(row_bytes, MAX_ROW_BYTES)
        # Within a segment, also send small chunks. With DTR wired up, each
        # chunk waits for the printer's ready signal; otherwise it's paced by
        # a fixed delay estimated from dot_print_time.
        chunk_rows = 16

        num_segments = max(1, num_segments)
        segment_height = max(1, -(-height // num_segments))  # ceil(height / num_segments)
        segment_starts = list(range(0, height, segment_height)) or [0]

        for i, seg_start in enumerate(segment_starts):
            seg_end = min(seg_start + segment_height, height)
            for row_start in range(seg_start, seg_end, chunk_rows):
                rows = min(chunk_rows, seg_end - row_start, MAX_CHUNK_ROWS)
                self._wait_ready()
                self._write(DC2, ord("*"), rows, row_bytes_clipped)
                chunk = bytearray()
                for y in range(row_start, row_start + rows):
                    offset = y * row_bytes
                    chunk += data[offset:offset + row_bytes_clipped]
                self._serial.write(chunk)
                self._serial.flush()
                if self._dtr is None:
                    time.sleep(rows * self._dot_print_time)
            if i < len(segment_starts) - 1:
                time.sleep(segment_delay)
        self._wait_ready()  # let the last chunk finish before feed()/close()

    def feed(self, lines=1):
        self._wait_ready()
        self._write(ESC, ord("d"), lines)
        time.sleep(lines * 0.05)

    def close(self):
        self._serial.close()
        if self._dtr is not None:
            self._dtr.close()


def print_image(
    data,
    width,
    height,
    port="/dev/serial0",
    baudrate=19200,
    feed_lines=3,
    num_segments=1,
    segment_delay=1.0,
    dtr_pin=DTR_PIN,
):
    """One-shot helper: open the printer, print a bitmap, feed paper, close."""
    printer = ThermalPrinter(port=port, baudrate=baudrate, dtr_pin=dtr_pin)
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
