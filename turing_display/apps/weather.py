"""Weather app (ported from apps/weather/weather_display.py).

Network fetches (OpenWeatherMap current + forecast) happen in ``update()`` and
are cached on ``self.weather_data``; the screen is drawn from that cache in
``render()``. All the custom icon-drawing and color helpers stay module-level.
"""

import math
from datetime import datetime

import requests
from PIL import Image, ImageDraw

from turing_display import SCREEN_WIDTH, SCREEN_HEIGHT
from turing_display.app_base import DisplayApp

# Units affect temperature color thresholds and formatting. Set by the app at
# construction; the original used a module-level UNITS global, kept here so the
# pure draw helpers stay module-level.
UNITS = 'metric'

# Colors
BG_COLOR = (20, 25, 35)
TEXT_COLOR = (255, 255, 255)
MUTED_COLOR = (110, 115, 130)
LINE_COLOR = (45, 55, 70)
RAIN_COLOR = (80, 160, 255)
SUN_COLOR = (255, 200, 50)
CLOUD_COLOR = (160, 170, 190)
SUNRISE_COLOR = (255, 180, 60)
SUNSET_COLOR = (200, 120, 60)

# Layout
L = 10
R = 310
CX = 160

# Section boundaries
HEADER_BOTTOM = 110
DETAILS_BOTTOM = 190
HOURLY_BOTTOM = 300
# Daily fills remaining to 480


# === Weather Icons (drawn as geometric shapes) ===

def draw_icon_sun(draw, cx, cy, r=7, color=SUN_COLOR):
    """Draw a sun: filled circle with rays."""
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=color)
    for angle in range(0, 360, 45):
        dx = math.cos(math.radians(angle))
        dy = math.sin(math.radians(angle))
        draw.line([
            (cx + dx * (r + 2), cy + dy * (r + 2)),
            (cx + dx * (r + 5), cy + dy * (r + 5)),
        ], fill=color, width=1)


def draw_icon_cloud(draw, cx, cy, color=CLOUD_COLOR):
    """Draw a cloud from overlapping ellipses."""
    draw.ellipse([(cx - 9, cy - 3), (cx + 1, cy + 5)], fill=color)
    draw.ellipse([(cx - 4, cy - 7), (cx + 6, cy + 2)], fill=color)
    draw.ellipse([(cx + 1, cy - 3), (cx + 11, cy + 5)], fill=color)
    draw.rectangle([(cx - 8, cy + 1), (cx + 10, cy + 5)], fill=color)


def draw_icon_rain(draw, cx, cy):
    """Draw cloud with rain drops."""
    draw_icon_cloud(draw, cx, cy - 4, CLOUD_COLOR)
    for dx in [-4, 2, 8]:
        draw.line([(cx + dx, cy + 4), (cx + dx - 2, cy + 9)], fill=RAIN_COLOR, width=1)


def draw_icon_drizzle(draw, cx, cy):
    """Draw cloud with light dots."""
    draw_icon_cloud(draw, cx, cy - 4, CLOUD_COLOR)
    for dx in [-3, 3]:
        draw.ellipse([(cx + dx - 1, cy + 5), (cx + dx + 1, cy + 7)], fill=RAIN_COLOR)


def draw_icon_thunder(draw, cx, cy):
    """Draw cloud with lightning bolt."""
    draw_icon_cloud(draw, cx, cy - 5, CLOUD_COLOR)
    # Lightning bolt
    draw.polygon([(cx, cy + 1), (cx + 3, cy + 1), (cx + 1, cy + 5),
                  (cx + 4, cy + 5), (cx - 1, cy + 11), (cx + 1, cy + 6),
                  (cx - 2, cy + 6)], fill=(255, 220, 50))


def draw_icon_snow(draw, cx, cy):
    """Draw cloud with snowflakes."""
    draw_icon_cloud(draw, cx, cy - 4, CLOUD_COLOR)
    for dx in [-4, 2, 8]:
        draw.ellipse([(cx + dx - 1, cy + 5), (cx + dx + 1, cy + 7)], fill=(200, 220, 255))


def draw_icon_mist(draw, cx, cy):
    """Draw horizontal wavy lines."""
    for i, dy in enumerate([-4, 0, 4]):
        w = 10 - i * 2
        draw.line([(cx - w, cy + dy), (cx + w, cy + dy)], fill=MUTED_COLOR, width=1)


def draw_icon_partial_cloud(draw, cx, cy):
    """Draw sun partially behind cloud."""
    draw_icon_sun(draw, cx - 3, cy - 3, r=6, color=SUN_COLOR)
    draw_icon_cloud(draw, cx + 2, cy + 1, CLOUD_COLOR)


def draw_weather_icon(draw, cx, cy, condition):
    """Draw the appropriate weather icon for a condition string."""
    key = condition.lower() if condition else 'clear'
    if key == 'clear':
        draw_icon_sun(draw, cx, cy)
    elif key == 'clouds':
        draw_icon_cloud(draw, cx, cy)
    elif key == 'rain':
        draw_icon_rain(draw, cx, cy)
    elif key == 'drizzle':
        draw_icon_drizzle(draw, cx, cy)
    elif key == 'thunderstorm':
        draw_icon_thunder(draw, cx, cy)
    elif key == 'snow':
        draw_icon_snow(draw, cx, cy)
    elif key in ('mist', 'fog', 'haze', 'smoke'):
        draw_icon_mist(draw, cx, cy)
    else:
        draw_icon_cloud(draw, cx, cy)


def draw_weather_icon_small(draw, cx, cy, condition):
    """Draw a smaller weather icon for forecast rows."""
    key = condition.lower() if condition else 'clear'
    if key == 'clear':
        r = 4
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=SUN_COLOR)
        for angle in range(0, 360, 60):
            dx = math.cos(math.radians(angle))
            dy = math.sin(math.radians(angle))
            draw.line([
                (cx + dx * (r + 1), cy + dy * (r + 1)),
                (cx + dx * (r + 3), cy + dy * (r + 3)),
            ], fill=SUN_COLOR, width=1)
    elif key in ('rain', 'drizzle'):
        # Tiny cloud + drops
        draw.ellipse([(cx - 5, cy - 4), (cx + 5, cy + 1)], fill=CLOUD_COLOR)
        for dx in [-2, 3]:
            draw.line([(cx + dx, cy + 2), (cx + dx - 1, cy + 5)], fill=RAIN_COLOR, width=1)
    elif key == 'thunderstorm':
        draw.ellipse([(cx - 5, cy - 4), (cx + 5, cy + 1)], fill=CLOUD_COLOR)
        draw.line([(cx, cy + 2), (cx - 1, cy + 6)], fill=(255, 220, 50), width=1)
    elif key == 'snow':
        draw.ellipse([(cx - 5, cy - 4), (cx + 5, cy + 1)], fill=CLOUD_COLOR)
        draw.ellipse([(cx - 1, cy + 3), (cx + 1, cy + 5)], fill=(200, 220, 255))
    elif key in ('mist', 'fog', 'haze', 'smoke'):
        for dy in [-2, 1, 4]:
            draw.line([(cx - 5, cy + dy), (cx + 5, cy + dy)], fill=MUTED_COLOR, width=1)
    else:
        draw.ellipse([(cx - 5, cy - 4), (cx + 5, cy + 1)], fill=CLOUD_COLOR)


# === Utility functions ===

def temp_color(temp_c):
    if UNITS == 'imperial':
        temp_c = (temp_c - 32) * 5 / 9
    if temp_c < 5:
        return (80, 140, 255)
    elif temp_c < 15:
        return (100, 220, 255)
    elif temp_c < 25:
        return (255, 255, 255)
    elif temp_c < 35:
        return (255, 180, 60)
    else:
        return (255, 70, 50)


def wind_direction(deg):
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
            'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return dirs[round(deg / 22.5) % 16]


def truncate_text(text, font, max_width):
    if font.getlength(text) <= max_width:
        return text
    while font.getlength(text + "..") > max_width and len(text) > 0:
        text = text[:-1]
    return text + ".." if text else ""


def format_temp(temp):
    unit = 'F' if UNITS == 'imperial' else 'C'
    return f"{temp:.0f}°{unit}"


def format_temp_short(temp):
    return f"{temp:.0f}°"


# === API functions ===

def fetch_current_weather(lat, lon, api_key, units):
    url = 'https://api.openweathermap.org/data/2.5/weather'
    params = {'lat': lat, 'lon': lon, 'appid': api_key, 'units': units}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_forecast(lat, lon, api_key, units):
    url = 'https://api.openweathermap.org/data/2.5/forecast'
    params = {'lat': lat, 'lon': lon, 'appid': api_key, 'units': units}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_all_weather(lat, lon, api_key, units):
    return {
        'current': fetch_current_weather(lat, lon, api_key, units),
        'forecast': fetch_forecast(lat, lon, api_key, units),
    }


def parse_hourly(forecast_data, count=8):
    if not forecast_data or 'list' not in forecast_data:
        return []
    now = datetime.now()
    entries = []
    for item in forecast_data['list']:
        dt = datetime.fromtimestamp(item['dt'])
        if dt <= now:
            continue
        condition = item['weather'][0]['main'] if item.get('weather') else 'Clear'
        entries.append({
            'time': dt, 'temp': item['main']['temp'],
            'pop': item.get('pop', 0), 'condition': condition,
        })
        if len(entries) >= count:
            break
    return entries


def parse_daily(forecast_data, count=4):
    if not forecast_data or 'list' not in forecast_data:
        return []
    today = datetime.now().date()
    days = {}
    for item in forecast_data['list']:
        dt = datetime.fromtimestamp(item['dt'])
        d = dt.date()
        if d <= today:
            continue
        if d not in days:
            days[d] = {'date': d, 'temps': [], 'pops': [], 'conditions': []}
        days[d]['temps'].append(item['main']['temp'])
        days[d]['pops'].append(item.get('pop', 0))
        days[d]['conditions'].append(item['weather'][0]['main'] if item.get('weather') else 'Clear')

    result = []
    for d in sorted(days.keys()):
        info = days[d]
        cond_counts = {}
        for c in info['conditions']:
            cond_counts[c] = cond_counts.get(c, 0) + 1
        main_cond = max(cond_counts, key=cond_counts.get)
        result.append({
            'date': d, 'high': max(info['temps']), 'low': min(info['temps']),
            'pop': min(1.0, max(info['pops'])), 'condition': main_cond,
        })
        if len(result) >= count:
            break
    return result


# === Drawing functions ===

def draw_header(draw, fonts, current, now, city_name):
    """Header: icon + hero temp + condition + feels like + city/time."""
    if not current:
        draw.text((CX, 50), 'Loading...', fill=MUTED_COLOR, font=fonts['medium'], anchor='mm')
        return

    weather = current.get('weather', [{}])[0]
    main_data = current.get('main', {})
    condition_main = weather.get('main', 'Clear')
    condition_text = weather.get('description', 'Unknown').title()
    temp = main_data.get('temp', 0)
    feels_like = main_data.get('feels_like', 0)

    # Top row: city left, time right
    city = city_name or current.get('name', 'Unknown')
    draw.text((L, 6), city, fill=MUTED_COLOR, font=fonts['small'], anchor='lt')
    draw.text((R, 6), now.strftime('%H:%M'), fill=MUTED_COLOR, font=fonts['small_mono'], anchor='rt')

    # Weather icon left of temp
    draw_weather_icon(draw, 42, 46, condition_main)

    # Hero temperature
    draw.text((CX + 20, 46), format_temp(temp), fill=temp_color(temp), font=fonts['temp_hero'], anchor='mm')

    # Condition
    draw.text((CX, 78), condition_text, fill=TEXT_COLOR, font=fonts['medium'], anchor='mm')

    # Feels like
    draw.text((CX, 98), f"Feels like {format_temp(feels_like)}", fill=MUTED_COLOR, font=fonts['small'], anchor='mm')


def draw_details(draw, fonts, current):
    """Current conditions: 2 rows x 3 columns."""
    if not current:
        return

    main_data = current.get('main', {})
    wind_data = current.get('wind', {})
    sys_data = current.get('sys', {})
    vis = current.get('visibility', 10000)
    clouds = current.get('clouds', {}).get('all', 0)

    humidity = main_data.get('humidity', 0)
    wind_speed = wind_data.get('speed', 0)
    wind_deg = wind_data.get('deg', 0)
    wind_dir = wind_direction(wind_deg)
    pressure = main_data.get('pressure', 0)
    speed_unit = 'mph' if UNITS == 'imperial' else 'm/s'

    sunrise = sys_data.get('sunrise')
    sunset = sys_data.get('sunset')
    sr_str = datetime.fromtimestamp(sunrise).strftime('%H:%M') if sunrise else '--:--'
    ss_str = datetime.fromtimestamp(sunset).strftime('%H:%M') if sunset else '--:--'

    if UNITS == 'imperial':
        vis_str = f'{vis / 1000 * 0.621:.1f}mi'
    else:
        vis_str = f'{vis / 1000:.1f}km'

    y = HEADER_BOTTOM + 6
    cols = [L + 50, CX, R - 50]

    # Row 1
    for i, (label, val) in enumerate([
        ('HUMIDITY', f'{humidity}%'),
        ('WIND', f'{wind_speed:.0f}{speed_unit} {wind_dir}'),
        ('PRESSURE', f'{pressure}'),
    ]):
        draw.text((cols[i], y), label, fill=MUTED_COLOR, font=fonts['label'], anchor='mt')
        draw.text((cols[i], y + 13), val, fill=TEXT_COLOR, font=fonts['value_mono'], anchor='mt')

    # Row 2
    y2 = y + 34
    for i, (label, val, color) in enumerate([
        ('VISIBILITY', vis_str, TEXT_COLOR),
        ('SUNRISE', sr_str, SUNRISE_COLOR),
        ('SUNSET', ss_str, SUNSET_COLOR),
    ]):
        draw.text((cols[i], y2), label, fill=MUTED_COLOR, font=fonts['label'], anchor='mt')
        draw.text((cols[i], y2 + 13), val, fill=color, font=fonts['value_mono'], anchor='mt')


def draw_hourly(draw, fonts, hourly):
    """Hourly forecast: 2 columns of 4, with icons."""
    y_base = DETAILS_BOTTOM + 6
    draw.text((L, y_base), 'HOURLY', fill=MUTED_COLOR, font=fonts['label'], anchor='lt')

    if not hourly:
        draw.text((CX, y_base + 50), 'No data', fill=MUTED_COLOR, font=fonts['small'], anchor='mm')
        return

    row_h = 22
    list_top = y_base + 16
    col_left = L
    col_right = CX + 8

    col_width = (R - L) // 2
    for i, entry in enumerate(hourly[:8]):
        col = i // 4
        row = i % 4
        x = col_left if col == 0 else col_right
        y = list_top + row * row_h
        col_end = x + col_width - 8

        # Small icon
        draw_weather_icon_small(draw, x + 6, y + 6, entry['condition'])

        # Time
        draw.text((x + 18, y), entry['time'].strftime('%H:%M'), fill=MUTED_COLOR, font=fonts['small_mono'], anchor='lt')

        # Temp (right-aligned within column to handle negatives)
        t_str = format_temp_short(entry['temp'])
        draw.text((x + 90, y), t_str, fill=temp_color(entry['temp']), font=fonts['value_mono'], anchor='rt')

        # Rain % (only if >=10%, with drop indicator)
        pop = entry['pop']
        if pop >= 0.10:
            pop_str = f'{int(pop * 100)}%'
            draw.text((col_end, y), pop_str, fill=RAIN_COLOR, font=fonts['small_mono'], anchor='rt')


def draw_daily(draw, fonts, daily):
    """Daily forecast: compact rows with icons."""
    y_base = HOURLY_BOTTOM + 6
    draw.text((L, y_base), 'FORECAST', fill=MUTED_COLOR, font=fonts['label'], anchor='lt')

    if not daily:
        draw.text((CX, y_base + 50), 'No data', fill=MUTED_COLOR, font=fonts['small'], anchor='mm')
        return

    row_h = 24
    list_top = y_base + 16
    days = daily[:4]

    # Calculate global temp range for bar scaling
    all_lows = [d['low'] for d in days]
    all_highs = [d['high'] for d in days]
    global_min = min(all_lows) if all_lows else 0
    global_max = max(all_highs) if all_highs else 10
    temp_span = max(1, global_max - global_min)

    # Layout columns: Day  Icon  Low  [---bar---]  High  Rain%
    icon_cx = 52
    low_x = 95        # low temp right-aligned here
    bar_left = 102
    bar_right = 226
    high_x = 232      # high temp left-aligned here
    rain_x = R         # rain % right-aligned here
    bar_width = bar_right - bar_left
    bar_h = 6

    for i, day in enumerate(days):
        y = list_top + i * row_h
        row_cy = y + 7

        # Day name
        draw.text((L, y), day['date'].strftime('%a'), fill=TEXT_COLOR, font=fonts['medium'], anchor='lt')

        # Icon
        draw_weather_icon_small(draw, icon_cx, row_cy, day['condition'])

        # Low temp (right-aligned, before bar)
        draw.text((low_x, y), format_temp_short(day['low']), fill=MUTED_COLOR, font=fonts['small_mono'], anchor='rt')

        # Temp range bar
        bar_y = row_cy - bar_h // 2
        draw.rounded_rectangle(
            [(bar_left, bar_y), (bar_right, bar_y + bar_h)],
            radius=3, fill=LINE_COLOR,
        )
        low_frac = (day['low'] - global_min) / temp_span
        high_frac = (day['high'] - global_min) / temp_span
        fill_x1 = bar_left + int(low_frac * bar_width)
        fill_x2 = bar_left + int(high_frac * bar_width)
        if fill_x2 > fill_x1:
            low_col = temp_color(day['low'])
            high_col = temp_color(day['high'])
            mid_col = (
                (low_col[0] + high_col[0]) // 2,
                (low_col[1] + high_col[1]) // 2,
                (low_col[2] + high_col[2]) // 2,
            )
            draw.rounded_rectangle(
                [(fill_x1, bar_y), (fill_x2, bar_y + bar_h)],
                radius=3, fill=mid_col,
            )

        # High temp (left-aligned, after bar)
        draw.text((high_x, y), format_temp_short(day['high']), fill=temp_color(day['high']), font=fonts['small_mono'], anchor='lt')

        # Rain % (right-aligned, only if >=10%)
        pop = min(1.0, day['pop'])
        if pop >= 0.10:
            draw.text((rain_x, y), f'{int(pop * 100)}%', fill=RAIN_COLOR, font=fonts['small_mono'], anchor='rt')

    # Extra info below forecast if space permits
    extra_y = list_top + len(daily[:4]) * row_h + 12
    if extra_y < 465:
        draw.line([(L, extra_y - 4), (R, extra_y - 4)], fill=LINE_COLOR, width=1)
        draw.text((CX, extra_y + 6), f'Updated {datetime.now().strftime("%H:%M")}', fill=MUTED_COLOR, font=fonts['label'], anchor='mt')


def draw_screen(now, weather_data, fonts, city_name):
    img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    current = weather_data.get('current')
    forecast = weather_data.get('forecast')
    hourly = parse_hourly(forecast, count=8)
    daily = parse_daily(forecast, count=4)

    draw_header(draw, fonts, current, now, city_name)
    draw.line([(L, HEADER_BOTTOM), (R, HEADER_BOTTOM)], fill=LINE_COLOR, width=1)

    draw_details(draw, fonts, current)
    draw.line([(L, DETAILS_BOTTOM), (R, DETAILS_BOTTOM)], fill=LINE_COLOR, width=1)

    draw_hourly(draw, fonts, hourly)
    draw.line([(L, HOURLY_BOTTOM), (R, HOURLY_BOTTOM)], fill=LINE_COLOR, width=1)

    draw_daily(draw, fonts, daily)

    return img


class WeatherApp(DisplayApp):
    name = 'weather'

    def __init__(self, ctx):
        super().__init__(ctx)

        owm = self.config['openweathermap']
        self.api_key = owm['api_key']
        self.lat = owm['latitude']
        self.lon = owm['longitude']
        self.units = owm.get('units', 'metric')
        self.city_name = owm.get('city_name', '')

        # Pure draw helpers read the module-level UNITS; keep it in sync.
        global UNITS
        UNITS = self.units

        self.update_interval = float(self.config.get('refresh_interval', 600))
        self.render_interval = 1.0  # clock in the header updates each second

        self.weather_data = None

        f = self.fonts.font
        # The original used Medium weights; the shared FontLoader only exposes
        # Regular/Bold, so Medium maps to Bold (closest available weight).
        self._fonts = {
            'temp_hero': f('roboto-mono-bold', 48),
            'medium': f('roboto-bold', 16),
            'small': f('roboto', 13),
            'label': f('roboto-bold', 10),
            'small_mono': f('roboto-mono-bold', 13),
            'value_mono': f('roboto-mono-bold', 15),
        }

    def update(self):
        try:
            data = fetch_all_weather(self.lat, self.lon, self.api_key, self.units)
        except Exception as e:
            print(f'[weather] fetch failed, keeping old data: {e}')
            return
        with self.lock:
            self.weather_data = data

    def render(self, now):
        with self.lock:
            data = self.weather_data
        if data is None:
            img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
            draw = ImageDraw.Draw(img)
            draw.text((CX, SCREEN_HEIGHT // 2), 'Loading weather…',
                      fill=MUTED_COLOR, font=self._fonts['medium'], anchor='mm')
            return img
        return draw_screen(now, data, self._fonts, self.city_name)
