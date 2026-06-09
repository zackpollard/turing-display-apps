"""App interface shared by every display module.

The runner owns the LCD, the diff/push pipeline, scheduling and the main loop.
An app only has to: fetch its data in ``update()`` (called on a background
thread on its own cadence) and turn current state into a 320x480 PIL image in
``render()`` (called from the main loop). State written in ``update()`` and
read in ``render()`` is guarded by ``self.lock``.
"""

import threading
from dataclasses import dataclass


@dataclass
class AppContext:
    """Everything an app needs from the runner, passed at construction."""
    fonts: object       # FontLoader
    config: dict        # this app's section of the config (apps.<name>)
    display: object     # Display, for brightness control
    width: int
    height: int

    def set_brightness(self, level):
        self.display.set_brightness(level)


class DisplayApp:
    """Base class for a display module.

    Subclasses set ``name`` and override ``update``/``render``. ``keep_warm``
    comes from per-app config and tells the scheduler whether to keep polling
    this app's data while it is hidden.
    """

    name = 'app'
    update_interval = 60.0   # seconds between data fetches while polling
    render_interval = 1.0    # min seconds between meaningful frames

    def __init__(self, ctx):
        self.ctx = ctx
        self.config = ctx.config
        self.fonts = ctx.fonts
        self.width = ctx.width
        self.height = ctx.height
        self.lock = threading.Lock()

    @property
    def keep_warm(self):
        return bool(self.config.get('keep_warm', False))

    def update(self):
        """Fetch data and store it on self (under self.lock). May block."""

    def render(self, now):
        """Return a (width x height) PIL Image for the current state."""
        raise NotImplementedError

    def on_show(self):
        """Called when this app becomes the active/visible one."""

    def on_hide(self):
        """Called when this app stops being the active one."""
