"""LCD lifecycle wrapper.

Owns the single ``LcdCommRevA`` serial connection. All operations that touch
the serial port (image pushes, brightness changes, screen off) are serialized
behind one lock, because the main render loop and the background update
threads (e.g. Spotify's auto-dim) can both reach the display concurrently.
"""

import threading

from PIL import Image

from library.lcd.lcd_comm_rev_a import LcdCommRevA
from library.lcd.lcd_comm import Orientation

from turing_display import SCREEN_WIDTH, SCREEN_HEIGHT


class Display:
    def __init__(self, com_port='AUTO', brightness=50):
        self._lock = threading.Lock()
        self._configured_brightness = brightness
        self._brightness = brightness
        self.lcd = LcdCommRevA(
            com_port=com_port,
            display_width=SCREEN_WIDTH,
            display_height=SCREEN_HEIGHT,
        )
        with self._lock:
            self.lcd.SetBrightness(level=brightness)
            self.lcd.SetOrientation(Orientation.PORTRAIT)
            self.lcd.DisplayPILImage(
                Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0)))

    def display_image(self, image, x=0, y=0):
        with self._lock:
            self.lcd.DisplayPILImage(image, x=int(x), y=int(y))

    def set_brightness(self, level):
        with self._lock:
            self._brightness = level
            self.lcd.SetBrightness(level=level)

    @property
    def brightness(self):
        return self._brightness

    @property
    def configured_brightness(self):
        return self._configured_brightness

    def close(self):
        """Restore configured brightness and blank the screen on shutdown."""
        with self._lock:
            try:
                self.lcd.SetBrightness(level=self._configured_brightness)
                self.lcd.DisplayPILImage(
                    Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), (0, 0, 0)))
            except Exception:
                pass
