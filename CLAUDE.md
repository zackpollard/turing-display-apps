# CLAUDE.md

## Project Overview

This is a collection of display applications for the Turing 3.5" USB-C smart screen (320x480, Revision A). The display is output-only (no touchscreen). It connects via USB serial at `/dev/ttyACM0` on Linux.

The repo lives at `git@github.com:zackpollard/turing-display-apps.git`.

## Repository Structure

```
turing-display-apps/
├── CLAUDE.md
├── README.md
├── LICENSE                          # GPL-3.0
├── requirements.txt
├── .gitignore                       # config.yaml is gitignored (contains credentials)
├── lib/
│   └── turing-smart-screen/         # Git submodule (mathoudebine/turing-smart-screen-python)
└── apps/
    └── calendar/
        ├── calendar_display.py      # Main script
        ├── config.example.yaml      # Template config (committed)
        ├── config.yaml              # Real config with credentials (gitignored, NEVER commit)
        └── README.md
```

## Key Technical Details

### Display Hardware
- Turing 3.5" Smart Screen, Revision A
- Resolution: 320x480 pixels, portrait orientation
- Communication: USB serial via `LcdCommRevA` from the submodule
- Serial port: `/dev/ttyACM0` (Linux), auto-detected by default
- User must be in `uucp` group on Arch Linux (or `dialout` on other distros) for serial access

### LCD Library (Submodule)
- Located at `lib/turing-smart-screen/`
- Upstream: https://github.com/mathoudebine/turing-smart-screen-python
- Not published as a standalone package, hence the submodule approach
- Key imports: `library.lcd.lcd_comm_rev_a.LcdCommRevA`, `library.lcd.lcd_comm.Orientation`
- Apps add the submodule to `sys.path` at runtime:
  ```python
  APP_DIR = os.path.dirname(__file__)
  ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
  sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))
  ```
- Fonts are loaded from `lib/turing-smart-screen/res/fonts/` (roboto, roboto-mono)

### Calendar App (`apps/calendar/`)
- Fetches events from Fastmail via CalDAV (`caldav` library + `vobject`)
- Supports multiple Fastmail accounts, merges and deduplicates events
- CalDAV URL pattern: `https://caldav.fastmail.com/dav/calendars/user/{email}/`
- Credentials are Fastmail app-specific passwords (not main account passwords)

#### Display Layout (320x480 portrait)
- **Header** (Y 0-140): Gradient background, date (Y=28), time with seconds (Y=75), event count (Y=122)
- **Divider line** at Y=140
- **Event rows** (Y 141-480): Up to 7 rows, each ROW_HEIGHT=48px
- Each row: time at X=25, title at X=95, separator line at bottom

#### Event States & Colors
- **Active** (currently happening): Green background `(30, 60, 40)`, green text `(50, 255, 100)`
- **Upcoming** (within 2 minutes): Flashes yellow/amber background, toggles every 0.5s
- **Tomorrow**: Purple text `(180, 140, 255)`, no background highlight
- **Normal**: Cyan time `(100, 200, 255)`, white title
- **Finished**: Filtered out, not displayed

#### Rendering Approach
- Full screen image is regenerated every frame using PIL
- Numpy-based diff compares current frame with previous frame
- Only changed row regions are sent to the display via `lcd.DisplayPILImage(region, x=0, y=y_start)`
- This avoids header corruption that occurred with naive partial updates
- Time updates every second, flash toggles every 0.5s, events refresh every 5 minutes

#### CalDAV Gotchas
- Some events use `DURATION` instead of `DTEND` - both must be handled
- Timezone handling: `dt.astimezone().replace(tzinfo=None)` converts to local naive datetime
- All-day events have `date` type (not `datetime`) for `dtstart` - check with `isinstance`
- Events are deduplicated by `(title, time, is_tomorrow)` tuple

### Visual Debugging
- A webcam pointed at the display can be used to verify rendering
- Capture: `ffmpeg -y -f v4l2 -i /dev/video1 -frames:v 1 /tmp/webcam_frame.jpg`
- Note: `/dev/video0` is typically the face camera, `/dev/video1` may be the external one

## Development Workflow

### Running
```bash
cd /home/zack/Source/turing-display-apps
source venv/bin/activate  # or create with: python -m venv venv && pip install -r requirements.txt
python apps/calendar/calendar_display.py
```

### Adding a New App
1. Create `apps/<name>/` directory
2. Add the `sys.path` boilerplate to access the LCD library (see above)
3. Add `config.example.yaml` (with placeholders only) and gitignore `config.yaml`
4. Each app should be self-contained with its own config and README

### Commits
- Use **conventional commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, etc.
- Include `Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>` when applicable

### Security
- **NEVER commit `config.yaml`** - it contains Fastmail app passwords
- Only `config.example.yaml` (with placeholder values) should be tracked
- Always verify with `git log --all -p | grep` before pushing
