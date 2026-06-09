"""Calendar app (ported from apps/calendar/calendar_display.py).

Fetches events from one or more Fastmail accounts via CalDAV in ``update()``
(network-heavy, runs on a background thread) and renders today's/tomorrow's
events in ``render()``. The upcoming-event highlight flashes every 0.5s.
"""

from datetime import datetime, date, timedelta

import caldav
from PIL import Image, ImageDraw

from turing_display import SCREEN_WIDTH, SCREEN_HEIGHT
from turing_display.app_base import DisplayApp

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

RSVP_COLORS = {
    'ACCEPTED': (50, 200, 80),
    'TENTATIVE': (220, 170, 30),
    'NEEDS-ACTION': (220, 170, 30),
    'DECLINED': (200, 50, 50),
    None: (100, 100, 100),
}
RSVP_DOT_X = 10
RSVP_DOT_RADIUS = 2


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


def get_my_partstat(vevent, my_emails):
    """Check RSVP status for any of my emails. Returns None if not an attendee."""
    if not hasattr(vevent, 'attendee'):
        return None
    attendees = vevent.attendee if isinstance(vevent.attendee, list) else [vevent.attendee]
    if my_emails:
        for attendee in attendees:
            email = str(attendee.value).replace('mailto:', '').strip().lower()
            if email in my_emails:
                return attendee.params.get('PARTSTAT', ['NEEDS-ACTION'])[0]
    # Event has attendees but we're not listed — check if we're the organizer
    # (organizers are implicitly accepted), or if it's on our calendar we've
    # accepted since Fastmail/JMAP strips the owner from the attendee list
    if hasattr(vevent, 'organizer'):
        org_email = str(vevent.organizer.value).replace('mailto:', '').strip().lower()
        if org_email in my_emails:
            return 'ACCEPTED'
    # On our calendar with attendees but we're not listed — Fastmail strips
    # the calendar owner from attendees, so treat as accepted
    return 'ACCEPTED'


def fetch_events(for_date, accounts, excluded_calendars, my_emails, hide_declined):
    """Fetch events for a specific date across all accounts."""
    events = []
    next_day = for_date + timedelta(days=1)

    for email, password, account_color in accounts:
        try:
            client = caldav.DAVClient(
                url=f'https://caldav.fastmail.com/dav/calendars/user/{email}/',
                username=email,
                password=password,
            )
            for cal in client.principal().calendars():
                if cal.name and cal.name.strip().lower() in excluded_calendars:
                    continue
                try:
                    for event in cal.search(
                        start=datetime.combine(for_date, datetime.min.time()),
                        end=datetime.combine(next_day, datetime.min.time()),
                        event=True, expand=True,
                    ):
                        try:
                            vevent = event.vobject_instance.vevent
                            partstat = get_my_partstat(vevent, my_emails)
                            if hide_declined and partstat == 'DECLINED':
                                continue
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
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception as e:
            print(f'Error fetching from {email}: {e}')

    return events


def fetch_all_events(accounts, excluded_calendars, my_emails, hide_declined):
    """Fetch today's and tomorrow's events, deduped and sorted."""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    all_events = (fetch_events(today, accounts, excluded_calendars, my_emails, hide_declined)
                  + fetch_events(tomorrow, accounts, excluded_calendars, my_emails, hide_declined))

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


def draw_gradient(draw, y_start, y_end):
    for y in range(y_start, y_end):
        progress = y / 150
        r = int(35 * (1 - progress * 0.5))
        g = int(45 * (1 - progress * 0.5))
        b = int(65 * (1 - progress * 0.5))
        draw.line([(0, y), (320, y)], fill=(r, g, b))


def draw_screen(now, events, flash_on, fonts, tomorrow_threshold):
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
    if len(today_events) <= tomorrow_threshold and tomorrow_events:
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


def parse_account_colors(acc):
    colors = acc.get('colors', {})
    return {k: tuple(v) for k, v in colors.items()} if colors else {}


class CalendarApp(DisplayApp):
    name = 'calendar'

    def __init__(self, ctx):
        super().__init__(ctx)

        self.accounts = [
            (acc['email'], acc['password'], parse_account_colors(acc))
            for acc in self.config.get('accounts', [])
        ]
        self.refresh_interval = float(self.config.get('refresh_interval', 300))
        self.tomorrow_threshold = self.config.get('tomorrow_threshold', 5)
        self.excluded_calendars = set(
            name.strip().lower() for name in self.config.get('excluded_calendars', [])
        )
        self.my_emails = set(e.strip().lower() for e in self.config.get('my_emails', []))
        self.my_emails.update(acc['email'].strip().lower() for acc in self.config.get('accounts', []))
        self.hide_declined = self.config.get('hide_declined', False)

        self.update_interval = self.refresh_interval
        self.render_interval = 0.5  # upcoming-event flash toggles every 0.5s

        f = self.fonts.font
        self._fonts = {
            'bold': f('roboto-bold', 22),
            'time': f('roboto-mono-bold', 36),
            'small': f('roboto', 16),
            'event_time': f('roboto-mono-bold', 18),
            'event': f('roboto', 18),
        }

        # None signals "never loaded" so render() can show a loading screen.
        self.events = None

    def update(self):
        try:
            events = fetch_all_events(
                self.accounts, self.excluded_calendars, self.my_emails, self.hide_declined
            )
        except Exception as e:
            print(f'Calendar update failed: {e}')
            return  # keep previously loaded events
        with self.lock:
            self.events = events

    def render(self, now):
        with self.lock:
            events = self.events
        if events is None:
            img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
            draw = ImageDraw.Draw(img)
            draw.text((160, 240), 'Loading calendar…', fill=MUTED_COLOR,
                      font=self._fonts['bold'], anchor='mm')
            return img
        flash_on = int(now.timestamp() * 2) % 2 == 0
        return draw_screen(now, events, flash_on, self._fonts, self.tomorrow_threshold)
