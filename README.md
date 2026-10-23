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
| Send bitmap to printer over serial | `print_image.py` |

Each module can also be run on its own for testing, e.g.
`python3 dither.py in.jpg out.png`.

## Wiring

- **Button:** GPIO 2 (pin 3) to GND. GPIO 2 already has a pull-up resistor on the board.
- **Printer:** printer RX to Pi TX (GPIO 14, pin 8), printer GND to Pi GND. Power the printer
  from its own 5–9 V, 2 A supply.
- **Camera:** IMX708 ribbon to the CSI port.

## Raspberry Pi setup

```sh
sudo apt install -y python3-picamera2 python3-gpiozero python3-serial python3-pil python3-numpy
sudo raspi-config   # Interface Options -> Serial Port: login shell NO, hardware YES
```

For Arducam IMX708 boards, add to `/boot/firmware/config.txt`, then reboot:

```
camera_auto_detect=0
dtoverlay=imx708
```

## Run

```sh
python3 main.py                       # defaults: 384 px tall, /dev/serial0 @ 19200
python3 main.py --height 384 --baud 9600 --gamma 0.75
```

Photos, dithered PNGs and HEX files are saved to `captures/`.

A 4:3 or 16:9 photo at 384 px tall is wider than the 384-dot print head, so
`main.py` rotates it 90° to print sideways along the paper. Check the printer's
self-test page (hold the feed button while powering it on) for its baud rate.
