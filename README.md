# pi-cam-printer

Press a button, take a photo with an Arducam IMX708, and print it as a dithered
1-bit image on an Adafruit Mini Thermal Receipt Printer.

## Pipeline

| Step | Module |
| --- | --- |
| Wait for button on GPIO 2 | `main.py` |
| Capture still photo | `take_photo.py` |
| Downscale to 384 px tall (`--height`) | `downscale.py` |
| Floyd-Steinberg serpentine dither to 1 bit | `dither.py` |
| Pack to printer bitmap + write HEX (`.h`) file | `convert_image.py` |
| Submit bitmap to the printer's CUPS queue | `print_image.py` |

Each module can also be run on its own for testing, e.g.
`python3 dither.py in.jpg out.png`.

## Wiring

- **Button:** GPIO 2 (pin 3) to GND. GPIO 2 already has a pull-up resistor on the board.
- **Printer:** printer RX to Pi TX (GPIO 14, pin 8), printer GND to Pi GND, printer DTR to
  GPIO 23 (pin 16, `--dtr-pin` to change). Power the printer from its own 5–9 V, 2 A supply.
  The DTR line runs at the printer's logic level (5 V on most of these boards), so put a
  voltage divider on it before it reaches the Pi's 3.3 V-only GPIO. Pass `--no-dtr` if your
  printer's cable doesn't have a DTR wire (the classic 3-wire "Mini" #597 doesn't).
- **Camera:** IMX708 ribbon to the CSI port.

## Raspberry Pi setup

```sh
sudo apt update
sudo apt install -y python3-picamera2 python3-gpiozero python3-cups python3-pil python3-numpy
sudo raspi-config   # Interface Options -> Serial Port: login shell NO, hardware YES
```

For Arducam IMX708 boards, add to `/boot/firmware/config.txt`, then reboot:

```
camera_auto_detect=0
dtoverlay=imx708
```

### Setting up the CUPS printer queue (one-time, OS-level)

`print_image.py` prints by submitting a raw job to a CUPS queue -- it does not
open the serial port itself -- so a queue for the printer has to exist before
`main.py` can print anything. This follows [Adafruit's CUPS guide](https://learn.adafruit.com/networked-thermal-printer-using-cups-and-raspberry-pi)
for this printer family:

```sh
sudo apt install -y cups system-config-printer libcups2-dev libcupsimage2-dev \
                     git build-essential cmake
sudo usermod -aG lpadmin $USER   # log out/in (or reboot) for this to take effect

# Build and install the ZJ-58 CUPS driver/filter for these ESC/POS printers
git clone https://github.com/klirichek/zj-58.git
cd zj-58 && mkdir build && cd build
cmake .. && cmake --build .
sudo make install                # restarts CUPS

# Find the installed PPD's exact CUPS identifier, then create the queue.
# Baud rate must match what the printer's self-test page reports (usually
# 19200); add &flow=soft to the URI to also enable the printer's own
# XON/XOFF flow control as extra protection against overrunning its buffer.
lpinfo -m | grep -i zj
sudo lpadmin -p ThermalPrinter -E \
    -v "serial:/dev/serial0?baud=19200" \
    -m <ppd identifier from the command above>
lpoptions -d ThermalPrinter       # make it the default, so --printer-name can be omitted
```

Test it directly with `echo "test" | lp -d ThermalPrinter` before running
`main.py`. If `lpadmin` isn't found or the printer doesn't show up in
`lpinfo -v`, re-check the raspi-config serial settings above -- CUPS's serial
backend needs the same `/dev/serial0` access the old direct-serial version did.

## Run

```sh
python3 main.py                                    # uses the CUPS default printer
python3 main.py --height 384 --printer-name ThermalPrinter --gamma 0.75
```

Photos, dithered PNGs and HEX files are saved to `captures/`.

A 4:3 or 16:9 photo at 384 px tall is wider than the 384-dot print head, so
`main.py` rotates it 90° to print sideways along the paper.

### Why CUPS, and what changes with it

Printing now goes through the OS's print spooler instead of this script
opening `/dev/serial0` itself: the printer becomes a normal, named print
destination (status, retry, and other apps can print to it too), and the baud
rate/device live in the CUPS queue's configuration rather than as `--port`/
`--baud` flags here (those flags are gone).

One real trade-off: the old direct-serial version paced its DTR checks and
delays between small 16-row chunks of a *single* continuous serial write.
Once CUPS's serial backend owns the device, this script can't interleave
writes like that -- each *segment* (`--segments`, default 1) is sent as one
complete CUPS job instead, with the DTR pin and `--segment-delay` only
checked between job submissions. That's coarser, and each extra segment costs
a full serial-port close/reopen. If a single-segment, DTR-paced print still
comes out garbled, try the `&flow=soft` queue option above instead, which
pushes the flow control down into the kernel's serial driver where it can
throttle every byte CUPS writes, not just the gaps between jobs.
