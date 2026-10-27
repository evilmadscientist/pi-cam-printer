"""Print a bitmap on a thermal receipt printer through the Raspberry Pi's CUPS
print system, instead of opening the serial port directly.

This module still builds the exact same raw ESC/POS bytes as before (the
``DC2 '*' rows rowBytes`` bitmap command used by the Adafruit Arduino
library's ``printBitmap()``), but hands them to a CUPS print queue as a RAW
job via pycups, instead of writing them to ``/dev/serial0`` with pyserial.
CUPS's own "serial" backend owns the device and does the actual writing.

This requires a one-time OS-level setup that is NOT done by this script --
see README.md for the full walkthrough. In short: a CUPS queue must already
exist, pointed at the printer's serial port (e.g. via
``lpadmin -v serial:/dev/serial0?baud=19200``), before this module can print
to it.

Why CUPS instead of talking to the serial port directly:
- The printer becomes a normal, named OS print destination with its own
  status/queue instead of a device file only one process can hold open.
- This script no longer needs permission to open /dev/serial0 itself, or to
  coordinate with anything else that might want to.
- Jobs are spooled, so a print survives this script restarting mid-job.

Trade-off vs. the direct-serial version: once CUPS's serial backend owns the
device, this module can't interleave live, per-chunk writes with GPIO DTR
checks the way the old print_bitmap() did (that required writing the bytes
itself, one small chunk at a time, waiting between each). Here, each
*segment* is sent as a single, complete CUPS job; the DTR pin is checked
between job submissions, not between every few rows. That's coarser than
before, and sending more than one segment costs an extra serial-port
open/close (and its short resync delay) per segment, which is why the
default is a single segment. If you still see garbled prints, consider
instead configuring XON/XOFF software flow control on the queue itself
(these printers support it; add ``&flow=soft`` to the device URI given to
``lpadmin``) -- that lets the kernel's serial driver throttle the CUPS
backend's writes automatically, with no per-job overhead.
"""

import os
import tempfile
import time

try:
    import cups
except ImportError:  # python3-cups not installed, or not running on the Pi
    cups = None

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
        printer_name=None,
        heat_dots=11,
        heat_time=120,
        heat_interval=40,
        dtr_pin=DTR_PIN,
        dtr_timeout=5.0,
    ):
        """Connect to CUPS and initialise the printer queue.

        printer_name: the CUPS queue to print to. None uses the CUPS default
        (``lpoptions -d``), or the only configured printer if there's just one.
        heat_time/heat_interval/heat_dots: see the printer's ESC/POS manual;
        higher heat_time/heat_interval = darker but slower.
        dtr_pin: BCM GPIO pin wired to the printer's DTR line, used to pace
        job submission. Pass None to disable and submit jobs back-to-back.
        dtr_timeout: max seconds to wait on the DTR line before giving up and
        continuing anyway, in case it's wired wrong or disconnected.
        """
        if cups is None:
            raise RuntimeError(
                "pycups is required to print via CUPS (sudo apt install python3-cups)"
            )
        self._conn = cups.Connection()
        self._printer_name = self._resolve_printer_name(printer_name)
        self._job_title_counter = 0

        self._dtr = None
        if dtr_pin is not None:
            if DigitalInputDevice is None:
                raise RuntimeError(
                    "gpiozero is required for DTR flow control (pip install gpiozero), "
                    "or pass dtr_pin=None to submit jobs without it"
                )
            # Idle/busy = HIGH, ready = LOW, so with pull_up=True "active" (pin
            # LOW) means "ready for more data" -- matching the printer's signal.
            self._dtr = DigitalInputDevice(dtr_pin, pull_up=True)
        self._dtr_timeout = dtr_timeout

        # Reset + heat config, and (if DTR is wired) the same command the
        # Adafruit Arduino library sends to make the printer start driving its
        # DTR pin. Submitted immediately as its own small job.
        init = bytearray([ESC, ord("@")])
        init += bytes([ESC, ord("7"), heat_dots, heat_time, heat_interval])
        init += bytes([DC2, ord("#"), (4 << 5) | 10])
        if self._dtr is not None:
            init += bytes([GS, ord("a"), 1 << 5])
        self._wait_ready()
        self._submit_job(bytes(init), "init")

    def _resolve_printer_name(self, printer_name):
        printers = self._conn.getPrinters()
        if printer_name is None:
            printer_name = self._conn.getDefault()
        if printer_name is None:
            if len(printers) == 1:
                printer_name = next(iter(printers))
            else:
                raise RuntimeError(
                    "No printer_name given and no CUPS default is set (lpoptions -d <name>). "
                    f"Configured printers: {', '.join(printers) or '(none)'}"
                )
        if printer_name not in printers:
            raise RuntimeError(
                f"CUPS printer {printer_name!r} not found. "
                f"Configured printers: {', '.join(printers) or '(none)'}. See README.md for setup."
            )
        return printer_name

    def _wait_ready(self):
        """Block until the printer's DTR line says it can accept more data."""
        if self._dtr is not None:
            self._dtr.wait_for_active(timeout=self._dtr_timeout)

    def _submit_job(self, payload, label):
        """Submit raw ESC/POS bytes to the CUPS queue as one print job."""
        self._job_title_counter += 1
        title = f"pi-cam-printer-{label}-{self._job_title_counter}"
        fd, path = tempfile.mkstemp(prefix="pi-cam-printer-", suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            # document-format=raw tells CUPS to pass the bytes straight to the
            # backend unfiltered, instead of treating them as a document to
            # rasterize with whatever driver the queue has installed.
            self._conn.printFile(self._printer_name, path, title,
                                  {"document-format": cups.CUPS_FORMAT_RAW})
        finally:
            os.unlink(path)

    def print_bitmap(self, data, width, height, num_segments=1, segment_delay=1.0):
        """Print packed bitmap rows (MSB = leftmost dot, 1 = black).

        Rows wider than the 384-dot print head are clipped on the right.

        The image is split into ``num_segments`` vertical segments (top to
        bottom), each submitted as its own CUPS job, in order, with a
        ``segment_delay`` second pause between submissions. See the module
        docstring for why this is coarser than the old per-chunk pacing.
        """
        row_bytes = (width + 7) // 8
        row_bytes_clipped = min(row_bytes, MAX_ROW_BYTES)

        num_segments = max(1, num_segments)
        segment_height = max(1, -(-height // num_segments))  # ceil(height / num_segments)
        segment_starts = list(range(0, height, segment_height)) or [0]

        for i, seg_start in enumerate(segment_starts):
            seg_end = min(seg_start + segment_height, height)
            payload = bytearray()
            # A segment can still exceed the printer's own max rows per
            # bitmap command, so split it into DC2 '*' blocks of at most
            # MAX_CHUNK_ROWS -- all within this one job.
            for row_start in range(seg_start, seg_end, MAX_CHUNK_ROWS):
                rows = min(MAX_CHUNK_ROWS, seg_end - row_start)
                payload += bytes([DC2, ord("*"), rows, row_bytes_clipped])
                for y in range(row_start, row_start + rows):
                    offset = y * row_bytes
                    payload += data[offset:offset + row_bytes_clipped]

            self._wait_ready()
            self._submit_job(bytes(payload), f"segment-{i}")
            if i < len(segment_starts) - 1:
                time.sleep(segment_delay)
        self._wait_ready()  # let the last segment finish before feed()

    def feed(self, lines=1):
        self._wait_ready()
        self._submit_job(bytes([ESC, ord("d"), lines]), "feed")
        time.sleep(lines * 0.05)

    def close(self):
        if self._dtr is not None:
            self._dtr.close()


def print_image(
    data,
    width,
    height,
    printer_name=None,
    feed_lines=3,
    num_segments=1,
    segment_delay=1.0,
    dtr_pin=DTR_PIN,
):
    """One-shot helper: connect to CUPS, print a bitmap, feed paper."""
    printer = ThermalPrinter(printer_name=printer_name, dtr_pin=dtr_pin)
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
