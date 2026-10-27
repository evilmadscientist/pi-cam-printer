"""Photo booth: press the button, take a photo, print it on the thermal printer.

Wiring: a push button between GPIO 2 (physical pin 3) and GND. GPIO 2 has a
built-in 1.8k pull-up on the Raspberry Pi, so the pin reads HIGH at rest and
LOW while the button is pressed.
"""

import argparse
import os
from datetime import datetime

from gpiozero import Button
from PIL import Image

from convert_image import convert_image
from dither import dither
from downscale import DEFAULT_HEIGHT, downscale
from print_image import DEFAULT_PORT, PRINTER_WIDTH_DOTS, print_image
from take_photo import Camera

BUTTON_GPIO = 2


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT,
                        help=f"downscaled image height in pixels (default {DEFAULT_HEIGHT})")
    parser.add_argument("--port", default=DEFAULT_PORT,
                        help=f"Teensy's USB serial port (default {DEFAULT_PORT})")
    parser.add_argument("--gamma", type=float, default=0.8,
                        help="gamma before dithering; <1 lightens to offset thermal dot gain")
    parser.add_argument("--output-dir", default="captures",
                        help="where to save photos and HEX files ('' to disable)")
    parser.add_argument("--test", action="store_true",
                        help="run the full sequence once immediately (no button press needed), then quit")
    return parser.parse_args()


def process(photo, args, stem=None):
    """Run the photo through downscale -> dither -> convert -> print."""
    small = downscale(photo, args.height)
    # The print head is 384 dots wide. If a landscape photo is too wide, turn it
    # sideways so its height runs across the paper.
    if small.width > PRINTER_WIDTH_DOTS and small.height <= PRINTER_WIDTH_DOTS:
        small = small.transpose(Image.Transpose.ROTATE_90)
    bw = dither(small, gamma=args.gamma)

    hex_path = None
    if stem:
        photo.save(stem + ".jpg")
        bw.save(stem + "_dithered.png")
        hex_path = stem + ".h"

    data, width, height = convert_image(bw, hex_path)
    print_image(data, width, height, port=args.port)


def capture_and_print(camera, args):
    """Take one photo and run it through the print pipeline."""
    print("Taking photo...")
    photo = camera.take_photo()
    stem = None
    if args.output_dir:
        stem = os.path.join(args.output_dir, datetime.now().strftime("%Y%m%d_%H%M%S"))
    print("Printing...")
    process(photo, args, stem)


def main():
    args = parse_args()
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    camera = Camera()
    button = None
    try:
        if args.test:
            print("Running test sequence...")
            capture_and_print(camera, args)
            print("Done.")
            return

        button = Button(BUTTON_GPIO, pull_up=True, bounce_time=0.05)
        print("Ready. Press the button to take a photo (Ctrl+C to quit).")
        while True:
            button.wait_for_press()  # idle until GPIO 2 is pulled LOW
            capture_and_print(camera, args)
            print("Done. Ready for the next photo.")
            button.wait_for_release()
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()
        if button:
            button.close()


if __name__ == "__main__":
    main()
