"""Capture a still photo from an Arducam IMX708 camera on the CSI port."""

import time

from picamera2 import Picamera2

try:
    from libcamera import controls
except ImportError:  # libcamera bindings ship with picamera2 on Raspberry Pi OS
    controls = None


class Camera:
    """Thin wrapper around Picamera2 that keeps the camera open between shots.

    Keeping the camera running avoids the ~1 s start-up cost and lets
    auto-exposure / auto-white-balance settle before the button is pressed.
    """

    def __init__(self, resolution=(2304, 1296)):
        self._picam2 = Picamera2()
        config = self._picam2.create_still_configuration(main={"size": resolution, "format": "RGB888"})
        self._picam2.configure(config)
        self._picam2.start()
        # The IMX708 (Camera Module 3 / Arducam IMX708) has a motorised lens.
        if controls is not None:
            self._picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        time.sleep(1.0)  # let AE/AWB converge

    def take_photo(self, save_path=None):
        """Capture a single frame and return it as a PIL RGB image."""
        if controls is not None:
            # Lock focus for this shot; falls back silently if unsupported.
            try:
                self._picam2.autofocus_cycle()
            except Exception:
                pass
        image = self._picam2.capture_image("main").convert("RGB")
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
    img = take_photo("photo.jpg")
    print(f"Saved photo.jpg ({img.width}x{img.height})")
