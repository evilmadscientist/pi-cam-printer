"""Capture a still photo from an Arducam IMX708 camera on the CSI port."""

import os
import re
import time

from picamera2 import Picamera2

try:
    from libcamera import controls
except ImportError:  # libcamera bindings ship with picamera2 on Raspberry Pi OS
    controls = None

PHOTO_DIR = "photo"
_FILENAME_RE = re.compile(r"^photo(?:_(\d+))?\.jpg$")


def _next_index(directory):
    """Return the next free index for photo.jpg / photo_1.jpg / photo_2.jpg... in directory."""
    max_index = -1
    if os.path.isdir(directory):
        for name in os.listdir(directory):
            m = _FILENAME_RE.match(name)
            if m:
                index = int(m.group(1)) if m.group(1) else 0
                max_index = max(max_index, index)
    return max_index + 1


class Camera:
    """Thin wrapper around Picamera2 that keeps the camera open between shots.

    Keeping the camera running avoids the ~1 s start-up cost and lets
    auto-exposure / auto-white-balance settle before the button is pressed.
    """

    def __init__(self, resolution=(2304, 1296), photo_dir=PHOTO_DIR):
        self._picam2 = Picamera2()
        config = self._picam2.create_still_configuration(main={"size": resolution, "format": "RGB888"})
        self._picam2.configure(config)
        self._picam2.start()
        # The IMX708 (Camera Module 3 / Arducam IMX708) has a motorised lens.
        if controls is not None:
            self._picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        time.sleep(1.0)  # let AE/AWB converge

        self._photo_dir = photo_dir
        os.makedirs(self._photo_dir, exist_ok=True)
        # Resume numbering after whatever photos already exist from earlier runs.
        self._next_index = _next_index(self._photo_dir)

    def _next_photo_path(self):
        index = self._next_index
        self._next_index += 1
        filename = "photo.jpg" if index == 0 else f"photo_{index}.jpg"
        return os.path.join(self._photo_dir, filename)

    def take_photo(self, save_path=None):
        """Capture a single frame, save it, and return it as a PIL RGB image.

        If ``save_path`` is omitted, the photo is auto-saved to the
        ``photo/`` subfolder with sequential filenames: ``photo.jpg``,
        ``photo_1.jpg``, ``photo_2.jpg``, ... Pass an explicit ``save_path``
        to save somewhere else instead, or ``save_path=False`` to skip saving.
        """
        if controls is not None:
            # Lock focus for this shot; falls back silently if unsupported.
            try:
                self._picam2.autofocus_cycle()
            except Exception:
                pass
        image = self._picam2.capture_image("main").convert("RGB")
        if save_path is None:
            save_path = self._next_photo_path()
        if save_path:
            image.save(save_path)
        return image

    def close(self):
        self._picam2.stop()
        self._picam2.close()


def take_photo(save_path=None, resolution=(2304, 1296)):
    """One-shot helper: open the camera, capture a photo, close the camera."""
    camera = Camera(resolution)
    try:
        return camera.take_photo(save_path)
    finally:
        camera.close()


if __name__ == "__main__":
    img = take_photo()
    print(f"Saved photo ({img.width}x{img.height}) to {PHOTO_DIR}/")
