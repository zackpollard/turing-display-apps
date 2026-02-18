# Fastmail Calendar Display

A calendar display for Turing 3.5" USB-C screens that shows your Fastmail calendar events.

## Features

- Live updating time display with seconds
- Shows today's calendar events from multiple Fastmail accounts
- Highlights active events in green
- Flashes upcoming events (within 2 minutes) in yellow/amber
- Automatically removes finished events
- Shows tomorrow's events when today has few remaining
- De-duplicates events across calendars
- Efficient diff-based screen updates

## Hardware

This project is designed for the Turing 3.5" Smart Screen (Revision A). Other revisions may work but are untested.

## Installation

1. Clone the repository with submodules:
   ```bash
   git clone --recurse-submodules https://github.com/yourusername/fastmail-calendar-display.git
   cd fastmail-calendar-display
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Copy the example config and add your credentials:
   ```bash
   cp config.example.yaml config.yaml
   ```

   Edit `config.yaml` with your Fastmail email and app-specific password.

   To generate an app password in Fastmail:
   - Go to Settings → Privacy & Security → Integrations
   - Create a new app password with CalDAV access

4. On Linux, ensure your user has access to the serial port:
   ```bash
   sudo usermod -aG dialout $USER  # or 'uucp' on Arch Linux
   ```
   Log out and back in for the group change to take effect.

## Usage

```bash
source venv/bin/activate
python calendar_display.py
```

Press Ctrl+C to stop.

## Configuration

See `config.example.yaml` for all available options:

- **accounts**: List of Fastmail accounts with email and app password
- **display.com_port**: Serial port (AUTO for auto-detection)
- **display.brightness**: Screen brightness 0-100
- **calendar.refresh_interval**: How often to fetch new events (seconds)
- **calendar.tomorrow_threshold**: Show tomorrow's events when today has this many or fewer

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This project uses [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) which is also GPL-3.0 licensed.
