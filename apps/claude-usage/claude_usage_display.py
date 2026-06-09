#!/usr/bin/env python3
"""Claude usage limits display for Turing 3.5" screen."""

import sys
import os

# Add the submodule to the path
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))

import json
import yaml
import sqlite3
import shutil
import subprocess
import time as time_module
from datetime import datetime, timezone
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from library.lcd.lcd_comm import Orientation
from PIL import Image, ImageDraw, ImageFont
import numpy as np


# Load configuration
def load_config():
    config_path = os.path.join(APP_DIR, 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# Display settings
COM_PORT = CONFIG['display'].get('com_port', 'AUTO')
BRIGHTNESS = CONFIG['display'].get('brightness', 50)

# Claude settings
CREDENTIALS_PATH = os.path.expanduser(
    CONFIG['claude'].get('credentials_path', '~/.claude/.credentials.json')
)
POLL_INTERVAL = CONFIG['claude'].get('poll_interval', 60)
ORG_ID = CONFIG['claude'].get('org_id', '')
FIREFOX_PROFILE = CONFIG['claude'].get('firefox_profile', '')

# Colors
BG_COLOR = (20, 25, 35)
TEXT_COLOR = (255, 255, 255)
MUTED_COLOR = (130, 135, 150)
LINE_COLOR = (50, 60, 80)
HEADER_ACCENT = (180, 140, 255)

# Layout
HEADER_H = 120
BAR_MARGIN_X = 30
BAR_WIDTH = 260  # 320 - 2*30
BAR_HEIGHT = 20
BAR_RADIUS = 5

# Font paths
FONT_DIR = os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen', 'res', 'fonts')


def bar_color(utilization):
    """Return color based on utilization percentage (0-100)."""
    if utilization < 50:
        return (50, 200, 120)
    elif utilization < 75:
        return (255, 200, 50)
    elif utilization < 90:
        return (255, 140, 50)
    else:
        return (255, 60, 60)


def bar_bg_color(utilization):
    """Return background color for bar based on utilization."""
    if utilization < 50:
        return (25, 50, 35)
    elif utilization < 75:
        return (50, 42, 18)
    elif utilization < 90:
        return (50, 35, 18)
    else:
        return (50, 22, 22)


def load_credentials():
    """Load Claude OAuth credentials for subscription/tier info."""
    try:
        with open(CREDENTIALS_PATH, 'r') as f:
            creds = json.load(f)
        oauth = creds.get('claudeAiOauth', {})
        return {
            'subscription': oauth.get('subscriptionType', 'unknown'),
            'tier': oauth.get('rateLimitTier', 'unknown'),
        }
    except Exception as e:
        print(f'Error loading credentials: {e}')
        return None


def find_firefox_cookies_db():
    """Find the Firefox cookies.sqlite file."""
    if FIREFOX_PROFILE:
        path = os.path.expanduser(FIREFOX_PROFILE)
        if os.path.isfile(path):
            return path
        cookies = os.path.join(path, 'cookies.sqlite')
        if os.path.isfile(cookies):
            return cookies

    ff_dir = os.path.expanduser('~/.mozilla/firefox')
    if not os.path.isdir(ff_dir):
        return None
    for entry in os.listdir(ff_dir):
        cookies = os.path.join(ff_dir, entry, 'cookies.sqlite')
        if os.path.isfile(cookies):
            return cookies
    return None


def get_firefox_session_cookie():
    """Extract claude.ai sessionKey and cf_clearance from Firefox cookies."""
    db_path = find_firefox_cookies_db()
    if not db_path:
        print('Could not find Firefox cookies database')
        return None

    tmp_path = '/tmp/claude_usage_ff_cookies.sqlite'
    try:
        shutil.copy2(db_path, tmp_path)
    except Exception as e:
        print(f'Error copying cookies db: {e}')
        return None

    try:
        conn = sqlite3.connect(tmp_path)
        sk_rows = conn.execute(
            "SELECT value FROM moz_cookies "
            "WHERE host LIKE '%claude.ai%' AND name='sessionKey' "
            "ORDER BY expiry DESC LIMIT 1"
        ).fetchall()
        cf_rows = conn.execute(
            "SELECT value FROM moz_cookies "
            "WHERE host LIKE '%claude.ai%' AND name='cf_clearance' "
            "ORDER BY expiry DESC LIMIT 1"
        ).fetchall()
        org_rows = conn.execute(
            "SELECT value FROM moz_cookies "
            "WHERE host LIKE '%claude.ai%' AND name='lastActiveOrg' "
            "ORDER BY expiry DESC LIMIT 1"
        ).fetchall()
        conn.close()

        session_key = sk_rows[0][0] if sk_rows else None
        cf_clearance = cf_rows[0][0] if cf_rows else ''
        org_from_cookie = org_rows[0][0] if org_rows else ''

        if not session_key:
            print('No sessionKey cookie found for claude.ai')
            return None

        return {
            'session_key': session_key,
            'cf_clearance': cf_clearance,
            'org_id': ORG_ID or org_from_cookie,
        }
    except Exception as e:
        print(f'Error reading cookies: {e}')
        return None


def fetch_usage(cookie_info):
    """Fetch usage data from the Claude.ai usage API."""
    org_id = cookie_info['org_id']
    if not org_id:
        print('No org_id configured or found in cookies')
        return None

    url = f'https://claude.ai/api/organizations/{org_id}/usage'
    cookie_str = f'sessionKey={cookie_info["session_key"]}'
    if cookie_info['cf_clearance']:
        cookie_str += f'; cf_clearance={cookie_info["cf_clearance"]}'
    cookie_str += f'; lastActiveOrg={org_id}'

    try:
        result = subprocess.run(
            [
                'curl', '-s',
                '-H', f'Cookie: {cookie_str}',
                '-H', 'User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0',
                '-H', 'Accept: application/json',
                url,
            ],
            capture_output=True, text=True, timeout=15,
        )

        if not result.stdout.strip():
            print('Empty response from usage API')
            return None

        data = json.loads(result.stdout)
        if 'error' in data:
            print(f'API error: {data}')
            return None

        windows = []
        for key, label in [
            ('five_hour', '5 Hour'),
            ('seven_day', '7 Day'),
            ('seven_day_sonnet', '7 Day Sonnet'),
            ('seven_day_opus', '7 Day Opus'),
            ('seven_day_oauth_apps', '7 Day OAuth'),
            ('seven_day_cowork', '7 Day Cowork'),
        ]:
            entry = data.get(key)
            if entry is not None:
                windows.append({
                    'label': label,
                    'utilization': entry['utilization'],
                    'resets_at': entry['resets_at'],
                })

        extra = data.get('extra_usage', {})
        return {
            'windows': windows,
            'extra_usage_enabled': extra.get('is_enabled', False) if extra else False,
            'fetched_at': time_module.time(),
        }

    except json.JSONDecodeError:
        print(f'Invalid JSON response (likely Cloudflare challenge)')
        return None
    except Exception as e:
        print(f'Error fetching usage: {e}')
        return None


def format_time_until(resets_at_str):
    """Format an ISO reset timestamp as 'Xd Xh Xm'."""
    try:
        reset_dt = datetime.fromisoformat(resets_at_str)
        now = datetime.now(timezone.utc)
        diff = (reset_dt - now).total_seconds()
        if diff <= 0:
            return 'now'
        days = int(diff // 86400)
        hours = int((diff % 86400) // 3600)
        minutes = int((diff % 3600) // 60)
        parts = []
        if days > 0:
            parts.append(f'{days}d')
        if hours > 0:
            parts.append(f'{hours}h')
        parts.append(f'{minutes}m')
        return ' '.join(parts)
    except Exception:
        return '?'


def format_tier(tier_str):
    """Format the rate limit tier name for display."""
    tier = tier_str.lower()
    if 'max_5x' in tier:
        return 'Max 5x'
    elif 'max' in tier:
        return 'Max'
    elif 'pro' in tier:
        return 'Pro'
    elif 'team' in tier:
        return 'Team'
    elif 'enterprise' in tier:
        return 'Enterprise'
    return tier_str


def draw_gradient(draw, y_start, y_end):
    """Draw header gradient."""
    for y in range(y_start, y_end):
        progress = y / y_end
        r = int(35 * (1 - progress * 0.4))
        g = int(28 * (1 - progress * 0.4))
        b = int(55 * (1 - progress * 0.4))
        draw.line([(0, y), (320, y)], fill=(r, g, b))


def draw_screen(now, creds, usage, fonts):
    """Draw the complete screen."""
    img = Image.new('RGB', (320, 480), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Header gradient
    draw_gradient(draw, 0, HEADER_H)

    # Title
    draw.text((160, 24), 'Claude Usage', fill=HEADER_ACCENT, font=fonts['title'], anchor='mm')

    # Subscription info
    if creds:
        tier_text = format_tier(creds['tier'])
        sub_text = creds['subscription'].title()
        draw.text((160, 50), f'{sub_text} \u2022 {tier_text}',
                  fill=TEXT_COLOR, font=fonts['medium'], anchor='mm')

    # Time
    draw.text((160, 78), now.strftime('%H:%M:%S'),
              fill=MUTED_COLOR, font=fonts['time'], anchor='mm')

    # Status indicator
    if usage and usage['windows']:
        max_util = max(w['utilization'] for w in usage['windows'])
        if max_util >= 100:
            status_color = (255, 60, 60)
            status_text = 'Rate Limited'
        elif max_util >= 80:
            status_color = (255, 140, 50)
            status_text = 'High Usage'
        else:
            status_color = (50, 200, 120)
            status_text = 'Active'
        dot_x = 160 - (fonts['small'].getlength(status_text) + 14) // 2
        draw.ellipse([(dot_x, 100), (dot_x + 8, 108)], fill=status_color)
        draw.text((dot_x + 14, 104), status_text,
                  fill=status_color, font=fonts['small'], anchor='lm')
    else:
        draw.text((160, 104), 'Connecting...',
                  fill=MUTED_COLOR, font=fonts['small'], anchor='mm')

    # Divider
    draw.line([(BAR_MARGIN_X, HEADER_H), (320 - BAR_MARGIN_X, HEADER_H)],
              fill=LINE_COLOR, width=1)

    if not usage or not usage['windows']:
        draw.text((160, 300), 'No data yet',
                  fill=MUTED_COLOR, font=fonts['medium'], anchor='mm')
        return img

    # Draw usage windows
    y = HEADER_H + 14

    for window in usage['windows']:
        utilization = window['utilization']
        label = window['label']
        resets_at = window['resets_at']

        # Label and percentage
        pct_text = f'{int(utilization)}%'
        draw.text((BAR_MARGIN_X, y), label,
                  fill=TEXT_COLOR, font=fonts['medium'], anchor='lm')
        draw.text((320 - BAR_MARGIN_X, y), pct_text,
                  fill=bar_color(utilization), font=fonts['medium'], anchor='rm')
        y += 28

        # Progress bar
        bar_top = y
        bar_bottom = y + BAR_HEIGHT
        draw.rounded_rectangle(
            (BAR_MARGIN_X, bar_top, 320 - BAR_MARGIN_X, bar_bottom),
            radius=BAR_RADIUS, fill=bar_bg_color(utilization))

        fill_frac = min(utilization / 100.0, 1.0)
        fill_width = max(int(BAR_WIDTH * fill_frac),
                         BAR_RADIUS * 2 if fill_frac > 0.01 else 0)
        if fill_width > 0:
            draw.rounded_rectangle(
                (BAR_MARGIN_X, bar_top, BAR_MARGIN_X + fill_width, bar_bottom),
                radius=BAR_RADIUS, fill=bar_color(utilization))

        y += BAR_HEIGHT

        # Reset time - centered between bar and separator
        gap = 34
        sep_y = y + gap
        text_y = y + gap // 2
        draw.text((BAR_MARGIN_X, text_y),
                  f'Resets in {format_time_until(resets_at)}',
                  fill=MUTED_COLOR, font=fonts['small'], anchor='lm')

        # Separator line
        draw.line([(BAR_MARGIN_X, sep_y), (320 - BAR_MARGIN_X, sep_y)],
                  fill=(35, 42, 55), width=1)
        y = sep_y + 14

    # Footer
    bottom_y = 455
    extra_enabled = usage.get('extra_usage_enabled', False)
    extra_text = 'Extra usage: on' if extra_enabled else 'Extra usage: off'
    draw.text((160, bottom_y), extra_text,
              fill=MUTED_COLOR, font=fonts['tiny'], anchor='mm')

    fetched = usage.get('fetched_at')
    if fetched:
        ago = int(time_module.time() - fetched)
        if ago < 60:
            ago_text = f'Updated {ago}s ago'
        else:
            ago_text = f'Updated {ago // 60}m ago'
        draw.text((160, bottom_y + 16), ago_text,
                  fill=(90, 95, 110), font=fonts['tiny'], anchor='mm')

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
    print('Loading configuration...', flush=True)
    print(f'  COM port: {COM_PORT}', flush=True)
    print(f'  Brightness: {BRIGHTNESS}%', flush=True)
    print(f'  Poll interval: {POLL_INTERVAL}s', flush=True)

    print('Loading credentials...', flush=True)
    creds = load_credentials()
    if creds:
        print(f'  Subscription: {creds["subscription"]}', flush=True)
        print(f'  Tier: {creds["tier"]}', flush=True)

    print('Connecting to display...', flush=True)
    lcd = LcdCommRevA(com_port=COM_PORT, display_width=320, display_height=480)
    lcd.SetBrightness(level=BRIGHTNESS)
    lcd.SetOrientation(Orientation.PORTRAIT)

    fonts = {
        'title': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 26),
        'medium': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 18),
        'time': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Bold.ttf'), 28),
        'small': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 14),
        'tiny': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 12),
    }

    # Clear screen on startup to remove stale content from prior runs
    clear_img = Image.new('RGB', (320, 480), BG_COLOR)
    lcd.DisplayPILImage(clear_img)

    # Retry initial fetch a few times (Firefox DB may be locked briefly)
    print('Fetching initial usage data...', flush=True)
    usage = None
    for attempt in range(3):
        cookie_info = get_firefox_session_cookie()
        if cookie_info:
            usage = fetch_usage(cookie_info)
            if usage:
                break
        if attempt < 2:
            print(f'  Retrying in 2s... (attempt {attempt + 2}/3)', flush=True)
            time_module.sleep(2)

    if usage:
        print(f'  Windows: {len(usage["windows"])}', flush=True)
        for w in usage['windows']:
            print(f'  {w["label"]}: {w["utilization"]:.0f}%', flush=True)
    else:
        print('  WARNING: Could not fetch usage data', flush=True)

    last_poll = time_module.time()
    last_second = -1

    # Initial draw
    now = datetime.now()
    current_img = draw_screen(now, creds, usage, fonts)
    lcd.DisplayPILImage(current_img)
    prev_img = current_img.copy()

    print('Running... (Ctrl+C to stop)', flush=True)
    try:
        while True:
            now = datetime.now()
            current_time = time_module.time()

            # Refresh usage periodically
            if current_time - last_poll > POLL_INTERVAL:
                last_poll = current_time
                cookie_info = get_firefox_session_cookie()
                if cookie_info:
                    new_usage = fetch_usage(cookie_info)
                    if new_usage:
                        usage = new_usage

            # Redraw every second (for clock and countdown updates)
            if now.second != last_second:
                last_second = now.second

                current_img = draw_screen(now, creds, usage, fonts)
                regions = find_changed_rows(prev_img, current_img)

                for y_start, y_end in regions:
                    region = current_img.crop((0, y_start, 320, y_end))
                    lcd.DisplayPILImage(region, x=0, y=y_start)

                prev_img = current_img.copy()

            time_module.sleep(0.05)
    except KeyboardInterrupt:
        print('\nStopping...', flush=True)


if __name__ == '__main__':
    main()
