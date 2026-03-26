#!/usr/bin/env python3
"""Calendar display for Turing 3.5" screen with Fastmail integration."""

import sys
import os

# Add the submodule to the path
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))

import caldav
import yaml
from datetime import datetime, date, timedelta
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from library.lcd.lcd_comm import Orientation
from PIL import Image, ImageDraw, ImageFont
import time as time_module
import numpy as np

# Load configuration
def load_config():
    config_path = os.path.join(APP_DIR, 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()
def parse_account_colors(acc):
    colors = acc.get('colors', {})
    return {k: tuple(v) for k, v in colors.items()} if colors else {}

ACCOUNTS = [(acc['email'], acc['password'], parse_account_colors(acc)) for acc in CONFIG['accounts']]

# Display settings
COM_PORT = CONFIG['display'].get('com_port', 'AUTO')
BRIGHTNESS = CONFIG['display'].get('brightness', 50)
REFRESH_INTERVAL = CONFIG['calendar'].get('refresh_interval', 300)
TOMORROW_THRESHOLD = CONFIG['calendar'].get('tomorrow_threshold', 5)
EXCLUDED_CALENDARS = set(name.strip().lower() for name in CONFIG['calendar'].get('excluded_calendars', []))
MY_EMAILS = set(e.strip().lower() for e in CONFIG['calendar'].get('my_emails', []))

# Colors
BG_COLOR = (20, 25, 35)
TEXT_COLOR = (255, 255, 255)
TIME_COLOR = (100, 200, 255)
MUTED_COLOR = (180, 180, 180)
LINE_COLOR = (60, 80, 100)
LINE_COLOR_DARK = (40, 50, 65)
UPCOMING_COLOR = (255, 200, 50)
UPCOMING_BG = (60, 50, 20)
UPCOMING_BG_OFF = (35, 30, 25)
ACTIVE_COLOR = (50, 255, 100)
ACTIVE_BG = (30, 60, 40)
TOMORROW_COLOR = (180, 140, 255)
TOMORROW_TIME_COLOR = (140, 100, 200)

# Layout
DATE_Y = 28
TIME_Y = 75
EVENT_COUNT_Y = 122
DIVIDER_Y = 140
EVENTS_START_Y = 148
ROW_HEIGHT = 48

# Font paths (relative to submodule)
FONT_DIR = os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen', 'res', 'fonts')


def truncate_text(text, font, max_width):
    if font.getlength(text) <= max_width:
        return text
    while font.getlength(text + "...") > max_width and len(text) > 0:
        text = text[:-1]
    return text + "..." if text else ""


def to_local_datetime(dt):
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return None
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def get_my_partstat(vevent):
    """Check RSVP status for any of my emails. Returns None if not an attendee."""
    if not MY_EMAILS or not hasattr(vevent, 'attendee'):
        return None
    attendees = vevent.attendee if isinstance(vevent.attendee, list) else [vevent.attendee]
    for attendee in attendees:
        email = str(attendee.value).replace('mailto:', '').strip().lower()
        if email in MY_EMAILS:
            return attendee.params.get('PARTSTAT', ['NEEDS-ACTION'])[0]
    return None


def fetch_events(for_date):
    """Fetch events for a specific date."""
    events = []
    next_day = for_date + timedelta(days=1)

    for email, password, account_color in ACCOUNTS:
        try:
            client = caldav.DAVClient(
                url=f'https://caldav.fastmail.com/dav/calendars/user/{email}/',
                username=email,
                password=password,
            )
            for cal in client.principal().calendars():
                if cal.name and cal.name.strip().lower() in EXCLUDED_CALENDARS:
                    continue
                try:
                    for event in cal.search(
                        start=datetime.combine(for_date, datetime.min.time()),
                        end=datetime.combine(next_day, datetime.min.time()),
                        event=True, expand=True,
                    ):
                        try:
                            vevent = event.vobject_instance.vevent
                            partstat = get_my_partstat(vevent)
                            summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else 'No title'
                            dtstart = vevent.dtstart.value
                            dtend = vevent.dtend.value if hasattr(vevent, 'dtend') else None
                            duration = vevent.duration.value if hasattr(vevent, 'duration') else None

                            if isinstance(dtstart, date) and not isinstance(dtstart, datetime):
                                events.append({
                                    'time': 'All day', 'title': summary,
                                    'start': datetime.combine(dtstart, datetime.min.time()),
                                    'end': datetime.combine(dtstart, datetime.max.time()),
                                    'is_all_day': True,
                                    'is_tomorrow': for_date != date.today(),
                                    'colors': account_color,
                                    'partstat': partstat,
                                })
                            else:
                                start_local = to_local_datetime(dtstart)
                                if dtend:
                                    end_local = to_local_datetime(dtend)
                                elif duration:
                                    end_local = start_local + duration
                                else:
                                    end_local = start_local + timedelta(hours=1)
                                events.append({
                                    'time': start_local.strftime('%H:%M'), 'title': summary,
                                    'start': start_local, 'end': end_local, 'is_all_day': False,
                                    'is_tomorrow': for_date != date.today(),
                                    'colors': account_color,
                                    'partstat': partstat,
                                })
                        except:
                            pass
                except:
                    pass
        except Exception as e:
            print(f'Error fetching from {email}: {e}')

    return events


def fetch_all_events():
    """Fetch today's and tomorrow's events."""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    all_events = fetch_events(today) + fetch_events(tomorrow)

    # Dedupe and sort
    seen = set()
    unique = []
    for e in all_events:
        key = (e['title'], e['time'], e.get('is_tomorrow', False))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: (x.get('is_tomorrow', False), not x['is_all_day'], x['start']))
    return unique


def get_event_state(event, now):
    if event['is_all_day']:
        return 'normal'
    if now > event['end']:
        return 'finished'
    if event['start'] <= now <= event['end']:
        return 'active'
    if 0 < (event['start'] - now).total_seconds() <= 120:
        return 'upcoming'
    return 'normal'


RSVP_COLORS = {
    'ACCEPTED': (50, 200, 80),
    'TENTATIVE': (220, 170, 30),
    'NEEDS-ACTION': (220, 170, 30),
    'DECLINED': (200, 50, 50),
    None: (100, 100, 100),
}
RSVP_DOT_X = 10
RSVP_DOT_RADIUS = 2


def draw_gradient(draw, y_start, y_end):
    for y in range(y_start, y_end):
        progress = y / 150
        r = int(35 * (1 - progress * 0.5))
        g = int(45 * (1 - progress * 0.5))
        b = int(65 * (1 - progress * 0.5))
        draw.line([(0, y), (320, y)], fill=(r, g, b))


def draw_screen(now, events, flash_on, fonts):
    """Draw the complete screen."""
    img = Image.new('RGB', (320, 480), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Header gradient
    draw_gradient(draw, 0, EVENTS_START_Y)

    # Date
    draw.text((160, DATE_Y), now.strftime('%A, %B %d'), fill=TEXT_COLOR, font=fonts['bold'], anchor='mm')

    # Time
    draw.text((160, TIME_Y), now.strftime('%H:%M:%S'), fill=TIME_COLOR, font=fonts['time'], anchor='mm')

    # Split events into today and tomorrow, filter finished
    today_events = [e for e in events if not e.get('is_tomorrow') and get_event_state(e, now) != 'finished']
    tomorrow_events = [e for e in events if e.get('is_tomorrow')]

    # Event count (today only)
    today_count = len(today_events)
    draw.text((160, EVENT_COUNT_Y), f"{today_count} event{'s' if today_count != 1 else ''} today",
              fill=MUTED_COLOR, font=fonts['small'], anchor='mm')

    # Divider
    draw.line([(20, DIVIDER_Y), (300, DIVIDER_Y)], fill=LINE_COLOR, width=1)

    # Build display list: today's events, then tomorrow's if space (7 rows available)
    display_events = today_events[:7]
    show_tomorrow_header = False
    if len(today_events) <= TOMORROW_THRESHOLD and tomorrow_events:
        show_tomorrow_header = True
        slots_for_tomorrow = 7 - len(today_events) - 1  # -1 for "Tomorrow" header
        display_events = today_events + [{'is_header': True}] + tomorrow_events[:slots_for_tomorrow]

    # Events - each row is ROW_HEIGHT pixels, starting right after divider
    row_index = 0
    for item in display_events[:7]:
        row_top = DIVIDER_Y + 1 + (row_index * ROW_HEIGHT)
        row_bottom = row_top + ROW_HEIGHT - 1
        text_y = (row_top + row_bottom) // 2

        if item.get('is_header'):
            # Tomorrow header row
            draw.rectangle([(20, row_top), (300, row_bottom)], fill=(35, 30, 45))
            draw.text((160, text_y), '— Tomorrow —', fill=TOMORROW_COLOR, font=fonts['small'], anchor='mm')
            draw.line([(20, row_bottom), (300, row_bottom)], fill=LINE_COLOR_DARK, width=1)
        else:
            event = item
            is_tomorrow = event.get('is_tomorrow', False)
            state = 'tomorrow' if is_tomorrow else get_event_state(event, now)

            ac = event.get('colors', {})

            if state == 'active':
                draw.rectangle([(20, row_top), (300, row_bottom)], fill=ac.get('active_bg', ACTIVE_BG))
                text_color = ac.get('active', ACTIVE_COLOR)
            elif state == 'upcoming':
                bg = ac.get('upcoming_bg', UPCOMING_BG) if flash_on else ac.get('upcoming_bg_off', UPCOMING_BG_OFF)
                draw.rectangle([(20, row_top), (300, row_bottom)], fill=bg)
                text_color = ac.get('upcoming', UPCOMING_COLOR) if flash_on else MUTED_COLOR
            elif state == 'tomorrow':
                text_color = ac.get('tomorrow', TOMORROW_COLOR)
            else:
                text_color = ac.get('today', TIME_COLOR)
            color = text_color
            title_color = text_color

            # RSVP indicator dot
            partstat = event.get('partstat')
            rsvp_color = RSVP_COLORS.get(partstat, RSVP_COLORS[None])
            if rsvp_color:
                dot_y = (row_top + row_bottom) // 2
                draw.ellipse(
                    [(RSVP_DOT_X - RSVP_DOT_RADIUS, dot_y - RSVP_DOT_RADIUS),
                     (RSVP_DOT_X + RSVP_DOT_RADIUS, dot_y + RSVP_DOT_RADIUS)],
                    fill=rsvp_color,
                )

            draw.text((25, text_y), event['time'], fill=color, font=fonts['event_time'], anchor='lm')
            time_width = fonts['event_time'].getlength(event['time'])
            title_x = max(95, 25 + int(time_width) + 10)
            title = truncate_text(event['title'], fonts['event'], 300 - title_x)
            draw.text((title_x, text_y), title, fill=title_color, font=fonts['event'], anchor='lm')
            draw.line([(20, row_bottom), (300, row_bottom)], fill=LINE_COLOR_DARK, width=1)

        row_index += 1

    if not display_events:
        draw.text((160, 300), 'No events', fill=MUTED_COLOR, font=fonts['bold'], anchor='mm')

    return img


def find_changed_rows(old_img, new_img):
    """Find rows that differ between two images."""
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


def main():
    print('Loading configuration...')
    print(f'  Accounts: {len(ACCOUNTS)}')
    print(f'  COM port: {COM_PORT}')
    print(f'  Brightness: {BRIGHTNESS}%')

    print('Connecting to display...')
    lcd = LcdCommRevA(com_port=COM_PORT, display_width=320, display_height=480)
    lcd.SetBrightness(level=BRIGHTNESS)
    lcd.SetOrientation(Orientation.PORTRAIT)

    fonts = {
        'bold': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 22),
        'time': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Bold.ttf'), 36),
        'small': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 16),
        'event_time': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Bold.ttf'), 18),
        'event': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 18),
    }

    print('Fetching events...')
    events = fetch_all_events()
    today_count = len([e for e in events if not e.get('is_tomorrow')])
    tomorrow_count = len([e for e in events if e.get('is_tomorrow')])
    print(f'Found {today_count} events today, {tomorrow_count} tomorrow')

    flash_on = True
    last_flash = time_module.time()
    last_fetch = time_module.time()
    last_second = -1

    # Initial draw
    now = datetime.now()
    current_img = draw_screen(now, events, flash_on, fonts)
    lcd.DisplayPILImage(current_img)
    prev_img = current_img.copy()

    print('Running... (Ctrl+C to stop)')
    try:
        while True:
            now = datetime.now()
            current_time = time_module.time()

            # Refresh events periodically
            if current_time - last_fetch > REFRESH_INTERVAL:
                last_fetch = current_time
                events = fetch_all_events()

            # Flash toggle
            if current_time - last_flash > 0.5:
                last_flash = current_time
                flash_on = not flash_on

            # Only redraw if something changed (time or flash)
            if now.second != last_second or flash_on != (not flash_on):
                last_second = now.second

                # Draw new frame
                current_img = draw_screen(now, events, flash_on, fonts)

                # Find changed regions
                regions = find_changed_rows(prev_img, current_img)

                # Send only changed regions
                for y_start, y_end in regions:
                    region = current_img.crop((0, y_start, 320, y_end))
                    lcd.DisplayPILImage(region, x=0, y=y_start)

                prev_img = current_img.copy()

            time_module.sleep(0.05)
    except KeyboardInterrupt:
        print('\nStopping...')


if __name__ == '__main__':
    main()
