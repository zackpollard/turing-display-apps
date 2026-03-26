#!/usr/bin/env python3
"""Weather display for Turing 3.5" screen with OpenWeatherMap integration."""

import sys
import os

# Add the submodule to the path
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))

import yaml
import requests
from datetime import datetime, timedelta
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from library.lcd.lcd_comm import Orientation
from PIL import Image, ImageDraw, ImageFont
import time as time_module
import numpy as np
import math

# Load configuration
def load_config():
    config_path = os.path.join(APP_DIR, 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()

API_KEY = CONFIG['openweathermap']['api_key']
LAT = CONFIG['openweathermap']['latitude']
LON = CONFIG['openweathermap']['longitude']
UNITS = CONFIG['openweathermap'].get('units', 'metric')
CITY_NAME = CONFIG['openweathermap'].get('city_name', '')

# Display settings
COM_PORT = CONFIG['display'].get('com_port', 'AUTO')
BRIGHTNESS = CONFIG['display'].get('brightness', 50)
REFRESH_INTERVAL = CONFIG['weather'].get('refresh_interval', 600)

# Colors
BG_COLOR = (20, 25, 35)
TEXT_COLOR = (255, 255, 255)
MUTED_COLOR = (150, 155, 165)
LINE_COLOR = (60, 80, 100)
LINE_COLOR_DARK = (40, 50, 65)
HEADER_ACCENT = (100, 200, 255)
RAIN_COLOR = (80, 150, 255)
HUMIDITY_BAR_BG = (40, 50, 65)
HUMIDITY_BAR_FG = (60, 160, 255)
WIND_COLOR = (160, 220, 240)
UV_LOW = (80, 200, 80)
UV_MOD = (240, 200, 50)
UV_HIGH = (255, 100, 50)
UV_EXTREME = (200, 50, 200)
PRESSURE_COLOR = (180, 180, 200)
VISIBILITY_COLOR = (180, 200, 180)
SECTION_LABEL_COLOR = (120, 140, 170)

# Weather condition symbols (ASCII, since Roboto lacks Unicode weather glyphs)
CONDITION_SYMBOLS = {
    'clear': '((',
    'clouds': '))',
    'rain': '//',
    'drizzle': ',,',
    'thunderstorm': '//!',
    'snow': '**',
    'mist': '~~',
    'fog': '~~',
    'haze': '~~',
    'smoke': '~~',
    'dust': '..',
    'sand': '..',
    'ash': '..',
    'squall': '//!',
    'tornado': '@@',
}

# Layout constants
HEADER_TOP = 0
HEADER_BOTTOM = 135
CONDITIONS_TOP = 140
CONDITIONS_BOTTOM = 258
HOURLY_TOP = 262
HOURLY_BOTTOM = 368
DAILY_TOP = 372
DAILY_BOTTOM = 480

# Font paths
FONT_DIR = os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen', 'res', 'fonts')


def temp_color(temp_c):
    """Return color based on temperature in Celsius."""
    if UNITS == 'imperial':
        # Convert F to C for color thresholds
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


def rain_prob_color(prob):
    """Return color for rain probability (0.0-1.0)."""
    intensity = int(80 + prob * 175)
    return (60, min(intensity, 180), 255)


def uv_color(uvi):
    """Return color based on UV index."""
    if uvi < 3:
        return UV_LOW
    elif uvi < 6:
        return UV_MOD
    elif uvi < 8:
        return UV_HIGH
    else:
        return UV_EXTREME


def wind_direction(deg):
    """Convert wind degree to compass direction."""
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
            'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    idx = round(deg / 22.5) % 16
    return dirs[idx]


def get_condition_symbol(main_condition):
    """Get a text symbol for a weather condition."""
    key = main_condition.lower() if main_condition else 'clear'
    return CONDITION_SYMBOLS.get(key, '?')


def truncate_text(text, font, max_width):
    if font.getlength(text) <= max_width:
        return text
    while font.getlength(text + "..") > max_width and len(text) > 0:
        text = text[:-1]
    return text + ".." if text else ""


def format_temp(temp):
    """Format temperature with unit symbol."""
    unit = 'F' if UNITS == 'imperial' else 'C'
    return f"{temp:.0f}°{unit}"


def fetch_current_weather():
    """Fetch current weather from OpenWeatherMap."""
    url = 'https://api.openweathermap.org/data/2.5/weather'
    params = {
        'lat': LAT, 'lon': LON,
        'appid': API_KEY, 'units': UNITS,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f'Error fetching current weather: {e}')
        return None


def fetch_forecast():
    """Fetch 5-day/3-hour forecast from OpenWeatherMap."""
    url = 'https://api.openweathermap.org/data/2.5/forecast'
    params = {
        'lat': LAT, 'lon': LON,
        'appid': API_KEY, 'units': UNITS,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f'Error fetching forecast: {e}')
        return None


def fetch_all_weather():
    """Fetch current weather and forecast, return combined data dict."""
    current = fetch_current_weather()
    forecast = fetch_forecast()
    return {'current': current, 'forecast': forecast}


def parse_hourly(forecast_data, count=8):
    """Extract next N hourly-ish entries from 3-hour forecast."""
    if not forecast_data or 'list' not in forecast_data:
        return []
    now = datetime.now()
    entries = []
    for item in forecast_data['list']:
        dt = datetime.fromtimestamp(item['dt'])
        if dt <= now:
            continue
        pop = item.get('pop', 0)
        temp = item['main']['temp']
        condition = item['weather'][0]['main'] if item.get('weather') else 'Clear'
        entries.append({
            'time': dt, 'temp': temp, 'pop': pop,
            'condition': condition, 'symbol': get_condition_symbol(condition),
        })
        if len(entries) >= count:
            break
    return entries


def parse_daily(forecast_data, count=4):
    """Aggregate 3-hour forecast into daily summaries."""
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
            days[d] = {
                'date': d, 'temps': [], 'pops': [], 'conditions': [],
            }
        days[d]['temps'].append(item['main']['temp'])
        days[d]['pops'].append(item.get('pop', 0))
        days[d]['conditions'].append(item['weather'][0]['main'] if item.get('weather') else 'Clear')

    result = []
    for d in sorted(days.keys()):
        info = days[d]
        # Most common condition
        cond_counts = {}
        for c in info['conditions']:
            cond_counts[c] = cond_counts.get(c, 0) + 1
        main_cond = max(cond_counts, key=cond_counts.get)
        result.append({
            'date': d,
            'high': max(info['temps']),
            'low': min(info['temps']),
            'pop': max(info['pops']),
            'condition': main_cond,
            'symbol': get_condition_symbol(main_cond),
        })
        if len(result) >= count:
            break
    return result


def draw_gradient(draw, y_start, y_end):
    """Draw header gradient matching calendar app style."""
    for y in range(y_start, y_end):
        progress = y / 150
        r = int(35 * (1 - progress * 0.5))
        g = int(45 * (1 - progress * 0.5))
        b = int(65 * (1 - progress * 0.5))
        draw.line([(0, y), (320, y)], fill=(r, g, b))


def draw_header(draw, fonts, current, now):
    """Draw the header section with current weather."""
    draw_gradient(draw, HEADER_TOP, HEADER_BOTTOM + 5)

    if not current:
        draw.text((160, 70), 'Loading...', fill=MUTED_COLOR, font=fonts['bold'], anchor='mm')
        return

    weather = current.get('weather', [{}])[0]
    main_data = current.get('main', {})
    condition_text = weather.get('description', 'Unknown').title()
    condition_main = weather.get('main', 'Clear')
    temp = main_data.get('temp', 0)
    feels_like = main_data.get('feels_like', 0)

    # City name
    city = CITY_NAME or current.get('name', 'Unknown')
    draw.text((160, 16), city, fill=MUTED_COLOR, font=fonts['small'], anchor='mm')

    # Current temperature (large, prominent)
    temp_str = format_temp(temp)
    draw.text((160, 56), temp_str, fill=temp_color(temp), font=fonts['temp_large'], anchor='mm')

    # Condition text
    draw.text((160, 92), condition_text, fill=TEXT_COLOR, font=fonts['medium'], anchor='mm')

    # Feels like
    feels_str = f"Feels like {format_temp(feels_like)}"
    draw.text((160, 114), feels_str, fill=MUTED_COLOR, font=fonts['small'], anchor='mm')

    # Time in top-right corner
    time_str = now.strftime('%H:%M')
    draw.text((305, 16), time_str, fill=HEADER_ACCENT, font=fonts['small_mono'], anchor='rm')


def draw_conditions(draw, fonts, current):
    """Draw current conditions section."""
    if not current:
        return

    y_base = CONDITIONS_TOP
    main_data = current.get('main', {})
    wind_data = current.get('wind', {})
    vis = current.get('visibility', 10000)

    # Section label
    draw.text((15, y_base + 2), 'CONDITIONS', fill=SECTION_LABEL_COLOR, font=fonts['tiny'], anchor='lt')
    draw.line([(15, y_base + 16), (305, y_base + 16)], fill=LINE_COLOR_DARK, width=1)

    row_y = y_base + 24
    row_h = 24
    col_mid = 160

    # Row 1: Humidity + Wind
    humidity = main_data.get('humidity', 0)
    draw.text((15, row_y), 'Humidity', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
    # Humidity bar
    bar_x = 70
    bar_w = 60
    bar_h = 8
    bar_y = row_y + 4
    draw.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], fill=HUMIDITY_BAR_BG)
    fill_w = int(bar_w * humidity / 100)
    if fill_w > 0:
        draw.rectangle([(bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h)], fill=HUMIDITY_BAR_FG)
    draw.text((bar_x + bar_w + 5, row_y), f'{humidity}%', fill=TEXT_COLOR, font=fonts['tiny'], anchor='lt')

    # Wind
    wind_speed = wind_data.get('speed', 0)
    wind_deg = wind_data.get('deg', 0)
    wind_dir = wind_direction(wind_deg)
    speed_unit = 'mph' if UNITS == 'imperial' else 'm/s'
    wind_str = f'{wind_speed:.0f}{speed_unit} {wind_dir}'
    draw.text((col_mid + 5, row_y), 'Wind', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
    draw.text((col_mid + 40, row_y), wind_str, fill=WIND_COLOR, font=fonts['tiny'], anchor='lt')

    row_y += row_h

    # Row 2: Pressure + Visibility
    pressure = main_data.get('pressure', 0)
    draw.text((15, row_y), 'Pressure', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
    draw.text((70, row_y), f'{pressure}hPa', fill=PRESSURE_COLOR, font=fonts['tiny'], anchor='lt')

    vis_km = vis / 1000
    if UNITS == 'imperial':
        vis_str = f'{vis_km * 0.621:.1f}mi'
    else:
        vis_str = f'{vis_km:.1f}km'
    draw.text((col_mid + 5, row_y), 'Visibility', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
    draw.text((col_mid + 62, row_y), vis_str, fill=VISIBILITY_COLOR, font=fonts['tiny'], anchor='lt')

    row_y += row_h

    # Row 3: Wind gust + Cloudiness
    gust = wind_data.get('gust')
    if gust:
        draw.text((15, row_y), 'Gust', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((70, row_y), f'{gust:.0f}{speed_unit}', fill=WIND_COLOR, font=fonts['tiny'], anchor='lt')

    clouds = current.get('clouds', {}).get('all', 0)
    draw.text((col_mid + 5, row_y), 'Clouds', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
    draw.text((col_mid + 48, row_y), f'{clouds}%', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')

    row_y += row_h

    # Row 4: Sunrise/Sunset
    sys_data = current.get('sys', {})
    sunrise = sys_data.get('sunrise')
    sunset = sys_data.get('sunset')
    if sunrise:
        sr = datetime.fromtimestamp(sunrise).strftime('%H:%M')
        draw.text((15, row_y), 'Rise', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((70, row_y), sr, fill=(255, 200, 80), font=fonts['tiny'], anchor='lt')
    if sunset:
        ss = datetime.fromtimestamp(sunset).strftime('%H:%M')
        draw.text((col_mid + 5, row_y), 'Set', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((col_mid + 32, row_y), ss, fill=(255, 140, 60), font=fonts['tiny'], anchor='lt')


def draw_hourly(draw, fonts, hourly):
    """Draw hourly forecast section."""
    y_base = HOURLY_TOP

    draw.text((15, y_base + 2), 'HOURLY', fill=SECTION_LABEL_COLOR, font=fonts['tiny'], anchor='lt')
    draw.line([(15, y_base + 16), (305, y_base + 16)], fill=LINE_COLOR_DARK, width=1)

    if not hourly:
        draw.text((160, y_base + 50), 'No data', fill=MUTED_COLOR, font=fonts['small'], anchor='mm')
        return

    # Show up to 8 hours in 2 rows of 4
    row_y = y_base + 22
    col_w = 73  # 4 columns across ~292px usable
    entries = hourly[:8]

    for i, entry in enumerate(entries):
        row = i // 4
        col = i % 4
        cx = 15 + col * col_w + col_w // 2
        cy = row_y + row * 44

        # Time
        time_str = entry['time'].strftime('%H:%M')
        draw.text((cx, cy), time_str, fill=MUTED_COLOR, font=fonts['tiny'], anchor='mt')

        # Temp
        t_str = f"{entry['temp']:.0f}"
        unit = 'F' if UNITS == 'imperial' else 'C'
        draw.text((cx, cy + 14), f'{t_str}°{unit}', fill=temp_color(entry['temp']), font=fonts['small_mono'], anchor='mt')

        # Rain probability
        pop = entry['pop']
        if pop > 0.05:
            pop_str = f'{int(pop * 100)}%'
            draw.text((cx, cy + 29), pop_str, fill=rain_prob_color(pop), font=fonts['tiny'], anchor='mt')


def draw_daily(draw, fonts, daily):
    """Draw daily forecast section."""
    y_base = DAILY_TOP

    draw.text((15, y_base + 2), 'FORECAST', fill=SECTION_LABEL_COLOR, font=fonts['tiny'], anchor='lt')
    draw.line([(15, y_base + 16), (305, y_base + 16)], fill=LINE_COLOR_DARK, width=1)

    if not daily:
        draw.text((160, y_base + 50), 'No data', fill=MUTED_COLOR, font=fonts['small'], anchor='mm')
        return

    row_y = y_base + 22
    row_h = 24

    for i, day in enumerate(daily[:4]):
        y = row_y + i * row_h

        # Day name
        day_name = day['date'].strftime('%a')
        draw.text((15, y), day_name, fill=TEXT_COLOR, font=fonts['small'], anchor='lt')

        # Condition symbol
        draw.text((60, y), day['symbol'], fill=HEADER_ACCENT, font=fonts['small'], anchor='lt')

        # High / Low
        high_str = f"{day['high']:.0f}"
        low_str = f"{day['low']:.0f}"
        draw.text((90, y), high_str, fill=temp_color(day['high']), font=fonts['small_mono'], anchor='lt')
        draw.text((130, y), '/', fill=MUTED_COLOR, font=fonts['small'], anchor='lt')
        draw.text((140, y), low_str, fill=temp_color(day['low']), font=fonts['small_mono'], anchor='lt')

        # Condition text
        cond = truncate_text(day['condition'], fonts['tiny'], 85)
        draw.text((185, y + 2), cond, fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')

        # Rain probability
        pop = min(1.0, day['pop'])
        if pop > 0.05:
            pop_str = f'{int(pop * 100)}%'
            draw.text((280, y + 2), pop_str, fill=rain_prob_color(pop), font=fonts['tiny'], anchor='lt')


def draw_screen(now, weather_data, fonts):
    """Draw the complete weather screen."""
    img = Image.new('RGB', (320, 480), BG_COLOR)
    draw = ImageDraw.Draw(img)

    current = weather_data.get('current')
    forecast = weather_data.get('forecast')

    # Parse forecast data
    hourly = parse_hourly(forecast, count=8)
    daily = parse_daily(forecast, count=4)

    # Draw sections
    draw_header(draw, fonts, current, now)
    draw.line([(15, HEADER_BOTTOM), (305, HEADER_BOTTOM)], fill=LINE_COLOR, width=1)

    draw_conditions(draw, fonts, current)
    draw.line([(15, CONDITIONS_BOTTOM), (305, CONDITIONS_BOTTOM)], fill=LINE_COLOR_DARK, width=1)

    draw_hourly(draw, fonts, hourly)
    draw.line([(15, HOURLY_BOTTOM), (305, HOURLY_BOTTOM)], fill=LINE_COLOR_DARK, width=1)

    draw_daily(draw, fonts, daily)

    return img


def find_changed_rows(old_img, new_img):
    """Find rows that differ between two images."""
    old_arr = np.array(old_img)
    new_arr = np.array(new_img)

    diff = np.any(old_arr != new_arr, axis=(1, 2))
    changed_rows = np.where(diff)[0]

    if len(changed_rows) == 0:
        return []

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
    print(f'  Location: {LAT}, {LON}')
    print(f'  Units: {UNITS}')
    print(f'  COM port: {COM_PORT}')
    print(f'  Brightness: {BRIGHTNESS}%')
    print(f'  Refresh interval: {REFRESH_INTERVAL}s')

    print('Connecting to display...')
    lcd = LcdCommRevA(com_port=COM_PORT, display_width=320, display_height=480)
    lcd.SetBrightness(level=BRIGHTNESS)
    lcd.SetOrientation(Orientation.PORTRAIT)
    lcd.DisplayPILImage(Image.new('RGB', (320, 480), (0, 0, 0)))

    fonts = {
        'temp_large': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 42),
        'bold': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 22),
        'medium': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Medium.ttf'), 18),
        'small': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 16),
        'tiny': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 13),
        'small_mono': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Medium.ttf'), 14),
        'symbol': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 28),
    }

    print('Fetching weather data...')
    weather_data = fetch_all_weather()
    if weather_data.get('current'):
        city = CITY_NAME or weather_data['current'].get('name', 'Unknown')
        temp = weather_data['current'].get('main', {}).get('temp', 0)
        print(f'  {city}: {temp:.1f} {"F" if UNITS == "imperial" else "C"}')

    last_fetch = time_module.time()
    last_second = -1

    # Initial draw
    now = datetime.now()
    current_img = draw_screen(now, weather_data, fonts)
    lcd.DisplayPILImage(current_img)
    prev_img = current_img.copy()

    print('Running... (Ctrl+C to stop)')
    try:
        while True:
            now = datetime.now()
            current_time = time_module.time()

            # Refresh weather data periodically
            if current_time - last_fetch > REFRESH_INTERVAL:
                last_fetch = current_time
                print(f'Refreshing weather data at {now.strftime("%H:%M:%S")}...')
                weather_data = fetch_all_weather()

            # Only redraw when the second changes (time display updates)
            if now.second != last_second:
                last_second = now.second

                current_img = draw_screen(now, weather_data, fonts)

                regions = find_changed_rows(prev_img, current_img)

                for y_start, y_end in regions:
                    region = current_img.crop((0, y_start, 320, y_end))
                    lcd.DisplayPILImage(region, x=0, y=y_start)

                prev_img = current_img.copy()

            time_module.sleep(0.05)
    except KeyboardInterrupt:
        print('\nStopping...')


if __name__ == '__main__':
    main()
