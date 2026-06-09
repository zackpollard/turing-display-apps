# Turing Display Apps

A collection of display applications for Turing 3.5" USB-C smart screens, run
from a single switchable [unified runner](#unified-runner).

## Available Apps

### Calendar
Fastmail calendar events with a live clock — today's events from multiple
accounts (de-duplicated), active events highlighted green, upcoming events
flashing, tomorrow's events when today is sparse, and RSVP-status dots.

### Weather
OpenWeatherMap current conditions, an hourly forecast, and a multi-day forecast
with hi/lo bars and hand-drawn weather icons.

### System Monitor
CPU (per-core bars + history graph + temperature), memory/swap, disk (with
optional ZFS pool stats), network speeds + graph, NVIDIA GPU, and top processes.

### Spotify
Now-playing with album art, accent colours sampled from the art, scrolling
track/artist text, progress bar, liked/shuffle/repeat indicators, an idle
"recently played" screen, and auto-dim while paused.

### Claude Usage
Anthropic subscription usage — rate-limit windows with colour-coded progress
bars and countdowns to reset.

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

## Unified Runner

All apps run inside a single long-lived process (`turing_display`) that owns the
display and switches between apps on demand. Switching reuses a persistent
framebuffer, so the differential renderer transfers only the rows that differ
between two apps' layouts — no slow full-screen clear/redraw on a switch.

```bash
cp config.example.yaml config.yaml   # then edit with your settings
python -m turing_display
```

The standalone `apps/*/`*`_display.py` scripts remain as reference; the runner
loads the ported modules from `turing_display/apps/`.

### Switching apps

The runner listens on a Unix socket; `bin/turing-ctl` is the client:

```bash
turing-ctl list             # show apps (active marked with *)
turing-ctl current          # name of the active app
turing-ctl next             # cycle forward
turing-ctl prev             # cycle backward
turing-ctl switch weather   # jump to a specific app
turing-ctl status
```

Bind these in your window manager. For sway:

```
bindsym $mod+Page_Down exec /path/to/turing-display-apps/bin/turing-ctl next
bindsym $mod+Page_Up   exec /path/to/turing-display-apps/bin/turing-ctl prev
bindsym $mod+w         exec /path/to/turing-display-apps/bin/turing-ctl switch weather
```

You can also script switches programmatically — e.g. `turing-ctl switch spotify`
from a media-player hook.

### Configuration

A single `config.yaml` (gitignored) holds the `display` settings, the `runner`
settings (app order, default app, socket path) and a per-app `apps:` section.
Each app supports `keep_warm: true` to keep polling its data source while hidden
(default is lazy — only the visible app polls, and a switch forces an immediate
refresh). See `config.example.yaml`.

### Running as a service

A user systemd unit is provided:

```bash
cp turing-display.service ~/.config/systemd/user/
systemctl --user enable --now turing-display.service
```

## Creating a New App

1. Add `turing_display/apps/<name>.py` defining a `DisplayApp` subclass
   (see `turing_display/app_base.py` and `turing_display/apps/sysmonitor.py`):
   - `update()` fetches data (runs on a background thread on its own cadence),
   - `render(now)` returns a 320×480 PIL image from the current state.
   The runner owns the LCD, the diff/push pipeline, fonts, config and the loop —
   your app never touches the serial port directly.
2. Register it in `turing_display/apps/__init__.py`.
3. Add an `apps.<name>` section to `config.yaml` / `config.example.yaml`.

## Future App Ideas

Potential apps that could be added:

**Productivity**
- Meeting countdown - prominent timer until next calendar event
- Task list - Todoist integration with today's tasks
- Pomodoro timer - work/break session tracking
- GitHub notifications - PRs awaiting review, CI build status

**Information**
- Public transit - next bus/train departures for your commute
- Package tracking - delivery status from various carriers
- News/RSS - scrolling headlines from your feeds

**Home & Environment**
- Home Assistant - temperature sensors, device status, doorbell alerts
- Air quality - indoor/outdoor AQI monitoring
- Smart home status - lights, locks, thermostat overview

**Communication**
- Email summary - unread counts per account
- Slack/Discord - notification summary and status

**Health**
- Hydration/stretch reminders - periodic prompts
- Standing desk timer - sit/stand interval tracking

**Entertainment**
- Photo frame - cycling through images from a folder

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

Uses [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) (GPL-3.0).
