"""Shared font loading.

Apps request fonts by logical family name + size; the loader caches each
``(family, size)`` so the Roboto TTFs are only parsed once for the whole
process regardless of how many apps use them.
"""

import os

from PIL import ImageFont

from turing_display import FONT_DIR

# Logical family name -> path relative to the submodule's res/fonts dir.
_FONT_FILES = {
    'roboto': 'roboto/Roboto-Regular.ttf',
    'roboto-bold': 'roboto/Roboto-Bold.ttf',
    'roboto-mono': 'roboto-mono/RobotoMono-Regular.ttf',
    'roboto-mono-bold': 'roboto-mono/RobotoMono-Bold.ttf',
}


class FontLoader:
    """Lazily loads and caches PIL fonts shared across all apps."""

    def __init__(self):
        self._cache = {}

    def font(self, family, size):
        key = (family, size)
        cached = self._cache.get(key)
        if cached is None:
            try:
                rel = _FONT_FILES[family]
            except KeyError:
                raise KeyError(f"unknown font family '{family}'; "
                               f"known: {sorted(_FONT_FILES)}")
            cached = ImageFont.truetype(os.path.join(FONT_DIR, rel), size)
            self._cache[key] = cached
        return cached
