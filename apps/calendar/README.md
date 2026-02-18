# Calendar Display

Displays your Fastmail calendar events on a Turing 3.5" screen.

## Features

- Live updating time display with seconds
- Shows today's calendar events from multiple Fastmail accounts
- Highlights active events in green
- Flashes upcoming events (within 2 minutes) in yellow/amber
- Automatically removes finished events
- Shows tomorrow's events when today has few remaining
- De-duplicates events across calendars
- Efficient diff-based screen updates

## Setup

1. Copy the example config:
   ```bash
   cp config.example.yaml config.yaml
   ```

2. Edit `config.yaml` with your Fastmail credentials.

   To generate an app password in Fastmail:
   - Go to Settings → Privacy & Security → Integrations
   - Create a new app password with CalDAV access

3. Run:
   ```bash
   python apps/calendar/calendar_display.py
   ```

## Configuration

See `config.example.yaml` for all options:

- **accounts**: List of Fastmail accounts with email and app password
- **display.com_port**: Serial port (AUTO for auto-detection)
- **display.brightness**: Screen brightness 0-100
- **calendar.refresh_interval**: How often to fetch new events (seconds)
- **calendar.tomorrow_threshold**: Show tomorrow's events when today has this many or fewer
