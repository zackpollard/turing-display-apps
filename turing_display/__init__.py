"""Unified runner for Turing 3.5" smart-screen display apps.

A single long-running process owns the LCD serial port and renders one of
several pluggable apps at a time. Switching between apps reuses a persistent
framebuffer so the scanline diff runs *across* apps -- only the rows that
actually differ are pushed to the display, making a switch as cheap as a
normal frame update instead of a full clear + redraw.
"""

import os
import sys

# Resolve repo paths and make the turing-smart-screen submodule importable.
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PACKAGE_DIR)
LIB_DIR = os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen')

if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

FONT_DIR = os.path.join(LIB_DIR, 'res', 'fonts')

# The Turing 3.5" Rev A is a fixed 320x480 portrait panel.
SCREEN_WIDTH = 320
SCREEN_HEIGHT = 480
