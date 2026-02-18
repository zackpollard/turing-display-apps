# Turing Display Apps

A collection of display applications for Turing 3.5" USB-C smart screens.

## Available Apps

### Calendar (`apps/calendar/`)
Displays your Fastmail calendar events with live updating time.

- Shows today's events from multiple Fastmail accounts
- Highlights active events in green
- Flashes upcoming events (within 2 minutes) in yellow
- Shows tomorrow's events when today has few remaining
- De-duplicates events across calendars

## Hardware

These apps are designed for the Turing 3.5" Smart Screen (Revision A). Other revisions may work but are untested.

## Installation

1. Clone the repository with submodules:
   ```bash
   git clone --recurse-submodules https://github.com/yourusername/turing-display-apps.git
   cd turing-display-apps
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. On Linux, ensure your user has access to the serial port:
   ```bash
   sudo usermod -aG dialout $USER  # or 'uucp' on Arch Linux
   ```
   Log out and back in for the group change to take effect.

## Running an App

Each app has its own directory under `apps/` with its own config file:

```bash
# Calendar app
cp apps/calendar/config.example.yaml apps/calendar/config.yaml
# Edit config.yaml with your settings
python apps/calendar/calendar_display.py
```

## Creating a New App

1. Create a new directory under `apps/`
2. Add your Python script and config files
3. Use the path setup from existing apps to access the LCD library:
   ```python
   import sys, os
   APP_DIR = os.path.dirname(__file__)
   ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
   sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))

   from library.lcd.lcd_comm_rev_a import LcdCommRevA
   ```

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

Uses [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) (GPL-3.0).
