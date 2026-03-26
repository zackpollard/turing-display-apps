#!/usr/bin/env python3
"""Spotify now-playing display for Turing 3.5" screen."""

import sys
import os

# Add the submodule to the path
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))

import yaml
import hashlib
import requests
import tempfile
import random
from datetime import datetime
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from library.lcd.lcd_comm import Orientation
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import time as time_module
import numpy as np
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Load configuration
def load_config():
    config_path = os.path.join(APP_DIR, 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# Spotify settings
SPOTIFY_CLIENT_ID = CONFIG['spotify']['client_id']
SPOTIFY_CLIENT_SECRET = CONFIG['spotify']['client_secret']
SPOTIFY_REDIRECT_URI = CONFIG['spotify'].get('redirect_uri', 'http://127.0.0.1:8888/callback')
SPOTIFY_SCOPE = 'user-read-playback-state user-read-currently-playing user-library-read user-read-recently-played'

# Display settings
COM_PORT = CONFIG['display'].get('com_port', 'AUTO')
BRIGHTNESS = CONFIG['display'].get('brightness', 50)
DIM_BRIGHTNESS = CONFIG['display'].get('dim_brightness', 10)
DIM_AFTER = CONFIG['display'].get('dim_after', 300)  # seconds of pause before dimming
POLL_INTERVAL = CONFIG.get('polling', {}).get('interval', 3)

# Colors
BG_COLOR = (20, 25, 35)
SPOTIFY_GREEN = (29, 185, 84)
TEXT_COLOR = (255, 255, 255)
ARTIST_COLOR = (180, 180, 180)
ALBUM_COLOR = (120, 120, 120)
MUTED_COLOR = (80, 80, 80)
PROGRESS_BG = (50, 55, 65)
STATUS_BG = (15, 18, 28)
PROGRESS_TIME_COLOR = (160, 160, 160)
LIKED_COLOR = (229, 57, 53)

# Layout
SCREEN_WIDTH = 320
SCREEN_HEIGHT = 480
ART_HEIGHT = 300
TRACK_INFO_Y = 305
TRACK_INFO_HEIGHT = 85
PROGRESS_Y = 395
PROGRESS_HEIGHT = 35
STATUS_Y = 435
STATUS_HEIGHT = 45

# Font paths
FONT_DIR = os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen', 'res', 'fonts')

# Art cache directory
ART_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'spotify-art-cache')
os.makedirs(ART_CACHE_DIR, exist_ok=True)

# Scrolling text config
SCROLL_SPEED = 2  # pixels per frame
SCROLL_PAUSE_FRAMES = 40  # frames to pause at start/end before scrolling


class ScrollState:
    """Tracks scrolling position for a text field."""
    def __init__(self):
        self.offset = 0
        self.pause_counter = SCROLL_PAUSE_FRAMES
        self.direction = 1  # 1 = scrolling left, -1 = scrolling right
        self.text = ""
        self.overflow = 0  # how many pixels the text overflows

    def reset(self, text, font, max_width):
        self.text = text
        text_width = font.getlength(text)
        self.overflow = max(0, int(text_width - max_width))
        self.offset = 0
        self.pause_counter = SCROLL_PAUSE_FRAMES
        self.direction = 1

    def update(self):
        if self.overflow <= 0:
            return 0
        if self.pause_counter > 0:
            self.pause_counter -= 1
            return self.offset
        self.offset += SCROLL_SPEED * self.direction
        if self.offset >= self.overflow:
            self.offset = self.overflow
            self.direction = -1
            self.pause_counter = SCROLL_PAUSE_FRAMES
        elif self.offset <= 0:
            self.offset = 0
            self.direction = 1
            self.pause_counter = SCROLL_PAUSE_FRAMES
        return self.offset


def truncate_text(text, font, max_width):
    if font.getlength(text) <= max_width:
        return text
    while font.getlength(text + "...") > max_width and len(text) > 0:
        text = text[:-1]
    return text + "..." if text else ""


def format_ms(ms):
    """Format milliseconds as M:SS."""
    total_seconds = max(0, int(ms / 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def get_dominant_color(img, sample_size=50):
    """Extract a dominant color from an image by sampling pixels."""
    small = img.resize((sample_size, sample_size), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    filtered = [(r, g, b) for r, g, b in pixels if 30 < r + g + b < 700]
    if not filtered:
        return BG_COLOR
    avg_r = sum(p[0] for p in filtered) // len(filtered)
    avg_g = sum(p[1] for p in filtered) // len(filtered)
    avg_b = sum(p[2] for p in filtered) // len(filtered)
    factor = 0.4
    return (
        int(BG_COLOR[0] + (avg_r - BG_COLOR[0]) * factor),
        int(BG_COLOR[1] + (avg_g - BG_COLOR[1]) * factor),
        int(BG_COLOR[2] + (avg_b - BG_COLOR[2]) * factor),
    )


def get_accent_color(img, sample_size=50):
    """Extract a vibrant accent color from album art for UI elements."""
    small = img.resize((sample_size, sample_size), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    # Find the most saturated color
    best = None
    best_score = 0
    for r, g, b in pixels:
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        if max_c == 0:
            continue
        sat = (max_c - min_c) / max_c
        lum = (r + g + b) / 3
        # Score: prefer saturated, mid-brightness colors
        score = sat * min(lum / 100, 1.0) * (1.0 - abs(lum - 140) / 200)
        if score > best_score and 40 < lum < 230:
            best_score = score
            best = (r, g, b)
    if best is None or best_score < 0.1:
        return SPOTIFY_GREEN
    # Boost brightness so it's visible on dark background
    r, g, b = best
    max_c = max(r, g, b)
    if max_c < 150:
        boost = 150 / max(max_c, 1)
        r = min(255, int(r * boost))
        g = min(255, int(g * boost))
        b = min(255, int(b * boost))
    return (r, g, b)


def download_art(url):
    """Download album art, with caching."""
    if not url:
        return None
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(ART_CACHE_DIR, f"{url_hash}.jpg")
    if os.path.exists(cache_path):
        try:
            return Image.open(cache_path).convert('RGB')
        except Exception:
            pass
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        with open(cache_path, 'wb') as f:
            f.write(resp.content)
        return Image.open(cache_path).convert('RGB')
    except Exception as e:
        print(f"Error downloading art: {e}")
        return None


def prepare_art(art_img):
    """Scale album art to fill 320px wide, center vertically in art area, apply gradient."""
    if art_img is None:
        return None
    w, h = art_img.size
    scale = SCREEN_WIDTH / w
    new_w = SCREEN_WIDTH
    new_h = int(h * scale)
    art_resized = art_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new('RGB', (SCREEN_WIDTH, ART_HEIGHT), BG_COLOR)
    y_offset = (ART_HEIGHT - new_h) // 2
    canvas.paste(art_resized, (0, y_offset))

    # Dark gradient at the bottom for blending into track info
    gradient = Image.new('RGBA', (SCREEN_WIDTH, ART_HEIGHT), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    gradient_start = ART_HEIGHT - 80
    for y in range(gradient_start, ART_HEIGHT):
        alpha = int(220 * ((y - gradient_start) / 80))
        grad_draw.line([(0, y), (SCREEN_WIDTH, y)], fill=(BG_COLOR[0], BG_COLOR[1], BG_COLOR[2], alpha))
    canvas = Image.alpha_composite(canvas.convert('RGBA'), gradient).convert('RGB')

    return canvas


def create_spotify_auth():
    """Create Spotify OAuth manager with token caching."""
    cache_path = os.path.join(APP_DIR, '.spotify_token_cache')
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE,
        cache_path=cache_path,
        open_browser=True,
    )


def get_playback_state(sp):
    """Fetch current playback state from Spotify."""
    try:
        playback = sp.current_playback()
        if playback is None:
            return None
        return playback
    except spotipy.exceptions.SpotifyException as e:
        print(f"Spotify API error: {e}")
        return None
    except Exception as e:
        print(f"Error fetching playback: {e}")
        return None


def check_liked(sp, track_id):
    """Check if a track is saved in the user's library."""
    try:
        result = sp.current_user_saved_tracks_contains([track_id])
        return result[0] if result else False
    except Exception:
        return False


def get_recently_played(sp, limit=5):
    """Get recently played tracks."""
    try:
        results = sp.current_user_recently_played(limit=limit)
        tracks = []
        for item in results.get('items', []):
            track = item.get('track', {})
            artists = ', '.join(a['name'] for a in track.get('artists', []))
            tracks.append({
                'name': track.get('name', 'Unknown'),
                'artists': artists,
            })
        return tracks
    except Exception:
        return []


def extract_track_info(playback):
    """Extract relevant track info from playback state."""
    if playback is None:
        return None
    item = playback.get('item')
    if item is None:
        return None

    # Get best album art URL (prefer 300px size)
    art_url = None
    images = item.get('album', {}).get('images', [])
    if images:
        images_sorted = sorted(images, key=lambda i: abs(i.get('width', 0) - 300))
        art_url = images_sorted[0].get('url')

    artists = ', '.join(a['name'] for a in item.get('artists', []))

    device = playback.get('device', {})

    # Release year from album
    release_date = item.get('album', {}).get('release_date', '')
    release_year = release_date[:4] if release_date else ''

    return {
        'track_name': item.get('name', 'Unknown'),
        'artists': artists,
        'album_name': item.get('album', {}).get('name', ''),
        'release_year': release_year,
        'art_url': art_url,
        'track_id': item.get('id', ''),
        'duration_ms': item.get('duration_ms', 0),
        'progress_ms': playback.get('progress_ms', 0),
        'is_playing': playback.get('is_playing', False),
        'shuffle': playback.get('shuffle_state', False),
        'repeat': playback.get('repeat_state', 'off'),
        'device_name': device.get('name', ''),
        'volume': device.get('volume_percent'),
    }


def draw_scrolling_text(img, draw, x, y, text, font, fill, max_width, scroll_offset, bg_color):
    """Draw text with scrolling offset, clipped to max_width."""
    text_width = font.getlength(text)
    if text_width <= max_width:
        draw.text((x, y), text, fill=fill, font=font)
    else:
        # Render full text onto a temp image, then crop the visible window
        h = 28
        txt_img = Image.new('RGB', (int(text_width) + 10, h), bg_color)
        txt_draw = ImageDraw.Draw(txt_img)
        txt_draw.text((0, 0), text, fill=fill, font=font)
        # Crop the visible portion based on scroll offset
        crop = txt_img.crop((int(scroll_offset), 0, int(scroll_offset) + int(max_width), h))
        img.paste(crop, (x, y))


def draw_idle_screen(fonts, recently_played=None):
    """Draw the idle/not playing screen."""
    img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Spotify branding
    center_y = 120
    draw.ellipse([(145, center_y - 15), (175, center_y + 15)], fill=SPOTIFY_GREEN)
    for i, offset in enumerate([(-6, 3), (-3, 5), (0, 7)]):
        y_off = offset[0]
        arc_w = offset[1]
        draw.arc(
            [(153 - arc_w, center_y + y_off - arc_w), (167 + arc_w, center_y + y_off + arc_w)],
            start=200, end=340,
            fill=(20, 25, 35), width=2
        )

    draw.text((160, center_y + 35), "Not Playing", fill=ARTIST_COLOR, font=fonts['track'], anchor='mm')

    # Recently played section
    if recently_played:
        draw.text((160, center_y + 70), "Recently Played", fill=MUTED_COLOR, font=fonts['status'], anchor='mm')
        draw.line([(40, center_y + 82), (280, center_y + 82)], fill=(40, 50, 65), width=1)

        for i, track in enumerate(recently_played[:5]):
            ty = center_y + 92 + i * 34
            name = truncate_text(track['name'], fonts['small'], SCREEN_WIDTH - 30)
            artist = truncate_text(track['artists'], fonts['status'], SCREEN_WIDTH - 30)
            draw.text((15, ty), name, fill=ARTIST_COLOR, font=fonts['small'])
            draw.text((15, ty + 16), artist, fill=MUTED_COLOR, font=fonts['status'])

    # Time at the bottom
    now = datetime.now()
    draw.text((160, 440), now.strftime('%H:%M'), fill=MUTED_COLOR, font=fonts['time_large'], anchor='mm')

    return img


def draw_playing_screen(track_info, art_canvas, tint_color, accent_color, fonts,
                        progress_now_ms, is_liked, scroll_states):
    """Draw the now-playing screen."""
    img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Album art
    if art_canvas is not None:
        img.paste(art_canvas, (0, 0))

    # Track info background with subtle tint
    for y in range(TRACK_INFO_Y, TRACK_INFO_Y + TRACK_INFO_HEIGHT):
        draw.line([(0, y), (SCREEN_WIDTH, y)], fill=tint_color)

    # Liked heart indicator
    info_left = 15
    if is_liked:
        hx = SCREEN_WIDTH - 22
        hy = TRACK_INFO_Y + 16
        r = 5
        # Two circles + triangle to form a heart
        draw.ellipse([(hx - r, hy - r), (hx, hy + 1)], fill=LIKED_COLOR)
        draw.ellipse([(hx, hy - r), (hx + r, hy + 1)], fill=LIKED_COLOR)
        draw.polygon([(hx - r, hy), (hx + r, hy), (hx, hy + r + 2)], fill=LIKED_COLOR)
        text_right_margin = 40
    else:
        text_right_margin = 20

    max_text_width = SCREEN_WIDTH - info_left - text_right_margin

    # Track name (scrolling if too long)
    track_name = track_info['track_name']
    track_scroll = scroll_states['track']
    if font_getlength(track_name, fonts['track']) > max_text_width:
        draw_scrolling_text(img, draw, info_left, TRACK_INFO_Y + 8, track_name,
                          fonts['track'], TEXT_COLOR, max_text_width, track_scroll.update(), tint_color)
    else:
        draw.text((info_left, TRACK_INFO_Y + 8), track_name, fill=TEXT_COLOR, font=fonts['track'])

    # Artist name (scrolling if too long)
    artists = track_info['artists']
    artist_scroll = scroll_states['artist']
    if font_getlength(artists, fonts['artist']) > max_text_width:
        draw_scrolling_text(img, draw, info_left, TRACK_INFO_Y + 36, artists,
                          fonts['artist'], ARTIST_COLOR, max_text_width, artist_scroll.update(), tint_color)
    else:
        draw.text((info_left, TRACK_INFO_Y + 36), artists, fill=ARTIST_COLOR, font=fonts['artist'])

    # Album name + release year
    album_text = track_info['album_name']
    if track_info.get('release_year'):
        album_text = f"{album_text} ({track_info['release_year']})"
    album_text = truncate_text(album_text, fonts['album'], max_text_width)
    draw.text((info_left, TRACK_INFO_Y + 62), album_text, fill=ALBUM_COLOR, font=fonts['album'])

    # Progress bar area background
    draw.rectangle([(0, PROGRESS_Y), (SCREEN_WIDTH, PROGRESS_Y + PROGRESS_HEIGHT)], fill=BG_COLOR)

    # Progress calculation
    duration_ms = track_info['duration_ms']
    if duration_ms > 0:
        progress_frac = min(1.0, max(0.0, progress_now_ms / duration_ms))
    else:
        progress_frac = 0

    # Progress bar
    bar_x_start = 55
    bar_x_end = SCREEN_WIDTH - 55
    bar_y = PROGRESS_Y + 14
    bar_height = 5
    bar_width = bar_x_end - bar_x_start

    # Use accent color for progress bar
    bar_color = accent_color

    draw.rounded_rectangle(
        [(bar_x_start, bar_y), (bar_x_end, bar_y + bar_height)],
        radius=2, fill=PROGRESS_BG,
    )
    filled_end = bar_x_start + int(bar_width * progress_frac)
    if filled_end > bar_x_start:
        draw.rounded_rectangle(
            [(bar_x_start, bar_y), (filled_end, bar_y + bar_height)],
            radius=2, fill=bar_color,
        )
    # Dot at current position
    dot_x = filled_end
    dot_r = 5
    draw.ellipse(
        [(dot_x - dot_r, bar_y + bar_height // 2 - dot_r),
         (dot_x + dot_r, bar_y + bar_height // 2 + dot_r)],
        fill=bar_color,
    )

    # Time labels
    elapsed = format_ms(progress_now_ms)
    total = format_ms(duration_ms)
    draw.text((bar_x_start - 5, bar_y + 2), elapsed, fill=PROGRESS_TIME_COLOR, font=fonts['time_small'], anchor='rm')
    draw.text((bar_x_end + 5, bar_y + 2), total, fill=PROGRESS_TIME_COLOR, font=fonts['time_small'], anchor='lm')

    # Paused indicator
    if not track_info['is_playing']:
        pause_y = bar_y - 12
        draw.text((160, pause_y), "PAUSED", fill=MUTED_COLOR, font=fonts['status'], anchor='mm')

    # Status bar
    draw.rectangle([(0, STATUS_Y), (SCREEN_WIDTH, SCREEN_HEIGHT)], fill=STATUS_BG)

    status_y_center = STATUS_Y + STATUS_HEIGHT // 2

    # Shuffle indicator
    shuffle_color = bar_color if track_info['shuffle'] else MUTED_COLOR
    draw.text((15, status_y_center), "SHF", fill=shuffle_color, font=fonts['status'], anchor='lm')

    # Repeat indicator
    repeat = track_info['repeat']
    if repeat == 'track':
        repeat_text = "RPT1"
        repeat_color = bar_color
    elif repeat == 'context':
        repeat_text = "RPT"
        repeat_color = bar_color
    else:
        repeat_text = "RPT"
        repeat_color = MUTED_COLOR
    draw.text((60, status_y_center), repeat_text, fill=repeat_color, font=fonts['status'], anchor='lm')

    # Device name
    device = truncate_text(track_info['device_name'], fonts['status'], 130)
    draw.text((160, status_y_center), device, fill=ALBUM_COLOR, font=fonts['status'], anchor='mm')

    # Volume
    if track_info['volume'] is not None:
        vol_text = f"VOL {track_info['volume']}%"
        draw.text((SCREEN_WIDTH - 15, status_y_center), vol_text, fill=ALBUM_COLOR, font=fonts['status'], anchor='rm')

    return img


def font_getlength(text, font):
    """Helper to get text length."""
    return font.getlength(text)


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
    print(f'  COM port: {COM_PORT}')
    print(f'  Brightness: {BRIGHTNESS}%')
    print(f'  Poll interval: {POLL_INTERVAL}s')

    print('Authenticating with Spotify...')
    auth_manager = create_spotify_auth()
    sp = spotipy.Spotify(auth_manager=auth_manager)
    try:
        user = sp.current_user()
        print(f'  Logged in as: {user["display_name"]} ({user["id"]})')
    except Exception as e:
        print(f'  Auth error: {e}')
        print('  Please check your credentials and re-authenticate.')
        return

    print('Connecting to display...')
    lcd = LcdCommRevA(com_port=COM_PORT, display_width=320, display_height=480)
    lcd.SetBrightness(level=BRIGHTNESS)
    lcd.SetOrientation(Orientation.PORTRAIT)
    lcd.DisplayPILImage(Image.new('RGB', (320, 480), (0, 0, 0)))

    fonts = {
        'track': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 22),
        'artist': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 18),
        'album': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Light.ttf'), 15),
        'time_small': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Regular.ttf'), 11),
        'time_large': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Bold.ttf'), 36),
        'status': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Medium.ttf'), 12),
        'small': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 14),
    }

    # State tracking
    current_track_id = None
    art_canvas = None
    tint_color = BG_COLOR
    accent_color = SPOTIFY_GREEN
    last_track_info = None
    last_poll = 0
    last_api_progress_ms = 0
    last_api_time = 0
    is_playing = False
    is_liked = False
    recently_played = None
    last_recent_fetch = 0
    is_dimmed = False
    last_playing_time = time_module.time()

    # Scroll states for track and artist names
    scroll_states = {
        'track': ScrollState(),
        'artist': ScrollState(),
    }

    # Fetch recently played for initial idle screen
    recently_played = get_recently_played(sp)

    # Initial draw
    current_img = draw_idle_screen(fonts, recently_played)
    lcd.DisplayPILImage(current_img)
    prev_img = current_img.copy()

    print('Running... (Ctrl+C to stop)')
    try:
        while True:
            current_time = time_module.time()

            # Poll Spotify at the configured interval
            if current_time - last_poll >= POLL_INTERVAL:
                last_poll = current_time
                playback = get_playback_state(sp)
                track_info = extract_track_info(playback)

                if track_info is not None:
                    last_track_info = track_info
                    was_playing = is_playing
                    is_playing = track_info['is_playing']
                    last_api_progress_ms = track_info['progress_ms']
                    last_api_time = current_time

                    if is_playing:
                        last_playing_time = current_time

                    # Track changed - download new art, check liked status
                    if track_info['track_id'] != current_track_id:
                        current_track_id = track_info['track_id']
                        print(f"Now playing: {track_info['track_name']} - {track_info['artists']}")
                        raw_art = download_art(track_info['art_url'])
                        art_canvas = prepare_art(raw_art)
                        if raw_art is not None:
                            tint_color = get_dominant_color(raw_art)
                            accent_color = get_accent_color(raw_art)
                        else:
                            tint_color = BG_COLOR
                            accent_color = SPOTIFY_GREEN
                        is_liked = check_liked(sp, track_info['track_id'])
                        # Reset scroll states for new track
                        max_text_width = SCREEN_WIDTH - 15 - (40 if is_liked else 20)
                        scroll_states['track'].reset(track_info['track_name'], fonts['track'], max_text_width)
                        scroll_states['artist'].reset(track_info['artists'], fonts['artist'], max_text_width)

                    # Un-dim when playback resumes
                    if is_playing and is_dimmed:
                        lcd.SetBrightness(level=BRIGHTNESS)
                        is_dimmed = False
                else:
                    is_playing = False
                    # Refresh recently played when idle (every 30s)
                    if current_time - last_recent_fetch > 30:
                        last_recent_fetch = current_time
                        recently_played = get_recently_played(sp)

            # Auto-dim after pause
            if not is_playing and not is_dimmed and (current_time - last_playing_time > DIM_AFTER):
                lcd.SetBrightness(level=DIM_BRIGHTNESS)
                is_dimmed = True

            # Interpolate progress between polls
            if last_track_info is not None and is_playing:
                elapsed_since_poll = (current_time - last_api_time) * 1000
                progress_now_ms = min(
                    last_api_progress_ms + elapsed_since_poll,
                    last_track_info['duration_ms']
                )
            elif last_track_info is not None:
                progress_now_ms = last_api_progress_ms
            else:
                progress_now_ms = 0

            # Draw the appropriate screen
            if last_track_info is not None:
                current_img = draw_playing_screen(
                    last_track_info, art_canvas, tint_color, accent_color, fonts,
                    progress_now_ms, is_liked, scroll_states
                )
            else:
                current_img = draw_idle_screen(fonts, recently_played)

            # Find changed regions and send to display
            regions = find_changed_rows(prev_img, current_img)
            for y_start, y_end in regions:
                region = current_img.crop((0, y_start, SCREEN_WIDTH, y_end))
                lcd.DisplayPILImage(region, x=0, y=y_start)

            prev_img = current_img.copy()

            # Sleep shorter when playing (for smooth progress bar + scrolling)
            if is_playing:
                time_module.sleep(0.15)
            else:
                time_module.sleep(0.5)

    except KeyboardInterrupt:
        print('\nStopping...')
        if is_dimmed:
            lcd.SetBrightness(level=BRIGHTNESS)


if __name__ == '__main__':
    main()
