# pi-cam-printer

Press a button, take a photo with an Arducam IMX708, and print it as a dithered
1-bit image on an Adafruit Mini Thermal Receipt Printer, driven by a Teensy 3.2.

## Pipeline

| Step | Where |
| --- | --- |
| Wait for button on GPIO 2 | `main.py` |
| Capture still photo | `take_photo.py` |
| Downscale to 384 px tall (`--height`) | `downscale.py` |
| Floyd-Steinberg serpentine dither to 1 bit | `dither.py` |
| Pack to printer bitmap + write HEX (`.h`) file | `convert_image.py` |
| Send bitmap to the Teensy over USB serial | `print_image.py` |
| Print it with DTR hardware flow control | `print_serial_image/print_serial_image.ino` (Teensy) |

Each Python module can also be run on its own for testing, e.g.
`python3 dither.py in.jpg out.png` or `python3 print_image.py dithered.png`.

## Wiring

- **Button:** GPIO 2 (pin 3) to GND. GPIO 2 already has a pull-up resistor on the board.
- **Teensy:** USB cable to the Pi. It shows up as `/dev/ttyACM0`.
- **Printer to Teensy:** printer RX to Teensy pin 1 (TX1), printer DTR to Teensy pin 4,
  printer GND to Teensy GND. The DTR wire comes from the "DTR" pad inside the printer, see
  [Adafruit's hacking guide](https://learn.adafruit.com/mini-thermal-receipt-printer/hacking).
  No level shifting is needed: the printer's logic is 3.3 V, and the Teensy 3.2's pins are
  3.3 V and 5 V tolerant. Power the printer from its own 5–9 V, 2 A supply.
- **Camera:** IMX708 ribbon to the CSI port.

## Teensy setup (Arduino IDE)

1. Install [Teensyduino](https://www.pjrc.com/teensy/td_download.html).
2. In Library Manager, install **Adafruit Thermal Printer Library**.
3. Open `print_serial_image/print_serial_image.ino`, choose **Tools > Board > Teensy 3.2 / 3.1**
   and **Tools > USB Type > Serial**, then upload.

Settings such as the DTR pin, the printer's baud rate (from its self-test page: hold the
feed button while powering it on) and heat settings are constants at the top of the sketch.
If the DTR wire isn't connected, set `USE_DTR` to `0`. Otherwise printing hangs, because the
pin reads as "busy" forever.

## Raspberry Pi setup

```sh
sudo apt update
sudo apt install -y python3-picamera2 python3-gpiozero python3-serial python3-pil python3-numpy
```

The printer no longer connects to the Pi's UART, so the serial port settings in
`raspi-config` don't matter. Your user needs to be in the `dialout` group to open
`/dev/ttyACM0` (the default user on Raspberry Pi OS already is).

For Arducam IMX708 boards, add to `/boot/firmware/config.txt`, then reboot:

```
camera_auto_detect=0
dtoverlay=imx708
```

## Run

```sh
python3 main.py                        # defaults: 384 px tall, Teensy on /dev/ttyACM0
python3 main.py --height 384 --port /dev/ttyACM1 --gamma 0.75
python3 main.py --test                 # one capture and print, no button needed
```

Photos, dithered PNGs and HEX files are saved to `captures/`.

A 4:3 or 16:9 photo at 384 px tall is wider than the 384-dot print head, so
`main.py` rotates it 90° to print sideways along the paper.

## Pi-to-Teensy protocol

All multi-byte values are little-endian. Replies from the Teensy end with a newline.

| Direction | Message |
| --- | --- |
| Pi → Teensy | `IMG1` + width (u16) + height (u16) + feed lines (u8) |
| Teensy → Pi | `READY`, or `ERR <reason>` |
| Pi → Teensy | bitmap: `ceil(width / 8) * height` bytes, MSB = leftmost dot, 1 = black |
| Pi → Teensy | `DONE` + checksum (u32, byte sum of the bitmap). This is the transfer-complete ack. |
| Teensy → Pi | `OK`, or `ERR <reason>`. Then the Teensy prints. |
| Teensy → Pi | `PRINTED` |

The Teensy buffers the whole image (up to 384 × 800 dots) before printing, so a slow or
interrupted USB transfer can never produce a half-printed image.
