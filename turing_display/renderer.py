"""Differential renderer with a persistent framebuffer.

This is the heart of the unified runner. It keeps the last image actually on
the panel (``framebuffer``) and never clears it on an app switch. Each
``push()`` diffs the new frame against the framebuffer row-by-row and sends
only the changed scanline regions. Because the framebuffer survives across
app switches, switching apps is just another ``push()`` -- only the rows that
genuinely differ between the two apps' layouts are transmitted.
"""

import numpy as np

from turing_display import SCREEN_WIDTH


def find_changed_rows(old_img, new_img):
    """Return a list of ``(y_start, y_end)`` regions of rows that differ.

    Lifted verbatim from the original per-app implementations (they were all
    identical) so there is now a single shared copy.
    """
    old_arr = np.array(old_img)
    new_arr = np.array(new_img)

    # Compare each row
    diff = np.any(old_arr != new_arr, axis=(1, 2))
    changed_rows = np.where(diff)[0]

    if len(changed_rows) == 0:
        return []

    # Group consecutive rows into regions
    regions = []
    start = changed_rows[0]
    end = changed_rows[0]

    for row in changed_rows[1:]:
        if row == end + 1:
            end = row
        else:
            regions.append((start, end + 1))
            start = row
            end = row
    regions.append((start, end + 1))

    return regions


class Renderer:
    def __init__(self, display):
        self.display = display
        self.framebuffer = None

    def push(self, image):
        """Diff ``image`` against the framebuffer and push only changed rows."""
        if self.framebuffer is None:
            self.display.display_image(image)
        else:
            for y_start, y_end in find_changed_rows(self.framebuffer, image):
                region = image.crop((0, int(y_start), SCREEN_WIDTH, int(y_end)))
                self.display.display_image(region, x=0, y=int(y_start))
        self.framebuffer = image
