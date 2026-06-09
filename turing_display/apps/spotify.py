"""Spotify now-playing app (ported from apps/spotify/spotify_display.py).

Split of responsibilities vs the original single loop:
  * update()  -> polls the Spotify API (playback, liked, recently-played,
                 album-art download on track change) on the poll interval.
  * render()  -> interpolates progress between polls, advances the scroll
                 animation, runs the auto-dim state machine (visible-only),
                 and draws the playing/idle screen.
  * on_hide() -> restores configured brightness so switching away never
                 leaves the panel dimmed.
"""

import hashlib
import os
import tempfile
import time as time_module

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from PIL import Image, ImageDraw

from turing_display import ROOT_DIR, SCREEN_WIDTH, SCREEN_HEIGHT
from turing_display.app_base import DisplayApp

SPOTIFY_SCOPE = ('user-read-playback-state user-read-currently-playing '
                 'user-library-read user-read-recently-played')

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
ART_HEIGHT = 300
TRACK_INFO_Y = 305
TRACK_INFO_HEIGHT = 85
PROGRESS_Y = 395
PROGRESS_HEIGHT = 35
STATUS_Y = 435
STATUS_HEIGHT = 45

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
    total_seconds = max(0, int(ms / 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def get_dominant_color(img, sample_size=50):
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
    small = img.resize((sample_size, sample_size), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    best = None
    best_score = 0
    for r, g, b in pixels:
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        if max_c == 0:
            continue
        sat = (max_c - min_c) / max_c
        lum = (r + g + b) / 3
        score = sat * min(lum / 100, 1.0) * (1.0 - abs(lum - 140) / 200)
        if score > best_score and 40 < lum < 230:
            best_score = score
            best = (r, g, b)
    if best is None or best_score < 0.1:
        return SPOTIFY_GREEN
    r, g, b = best
    max_c = max(r, g, b)
    if max_c < 150:
        boost = 150 / max(max_c, 1)
        r = min(255, int(r * boost))
        g = min(255, int(g * boost))
        b = min(255, int(b * boost))
    return (r, g, b)


def download_art(url):
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

    gradient = Image.new('RGBA', (SCREEN_WIDTH, ART_HEIGHT), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    gradient_start = ART_HEIGHT - 80
    for y in range(gradient_start, ART_HEIGHT):
        alpha = int(220 * ((y - gradient_start) / 80))
        grad_draw.line([(0, y), (SCREEN_WIDTH, y)], fill=(BG_COLOR[0], BG_COLOR[1], BG_COLOR[2], alpha))
    canvas = Image.alpha_composite(canvas.convert('RGBA'), gradient).convert('RGB')

    return canvas


def get_playback_state(sp):
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
    try:
        result = sp.current_user_saved_tracks_contains([track_id])
        return result[0] if result else False
    except Exception:
        return False


def get_recently_played(sp, limit=5):
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
    if playback is None:
        return None
    item = playback.get('item')
    if item is None:
        return None

    art_url = None
    images = item.get('album', {}).get('images', [])
    if images:
        images_sorted = sorted(images, key=lambda i: abs(i.get('width', 0) - 300))
        art_url = images_sorted[0].get('url')

    artists = ', '.join(a['name'] for a in item.get('artists', []))
    device = playback.get('device', {})
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


def font_getlength(text, font):
    return font.getlength(text)


def draw_scrolling_text(img, draw, x, y, text, font, fill, max_width, scroll_offset, bg_color):
    text_width = font.getlength(text)
    if text_width <= max_width:
        draw.text((x, y), text, fill=fill, font=font)
    else:
        h = 28
        txt_img = Image.new('RGB', (int(text_width) + 10, h), bg_color)
        txt_draw = ImageDraw.Draw(txt_img)
        txt_draw.text((0, 0), text, fill=fill, font=font)
        crop = txt_img.crop((int(scroll_offset), 0, int(scroll_offset) + int(max_width), h))
        img.paste(crop, (x, y))


def draw_idle_screen(now, fonts, recently_played=None):
    img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

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

    if recently_played:
        draw.text((160, center_y + 70), "Recently Played", fill=MUTED_COLOR, font=fonts['status'], anchor='mm')
        draw.line([(40, center_y + 82), (280, center_y + 82)], fill=(40, 50, 65), width=1)

        for i, track in enumerate(recently_played[:5]):
            ty = center_y + 92 + i * 34
            name = truncate_text(track['name'], fonts['small'], SCREEN_WIDTH - 30)
            artist = truncate_text(track['artists'], fonts['status'], SCREEN_WIDTH - 30)
            draw.text((15, ty), name, fill=ARTIST_COLOR, font=fonts['small'])
            draw.text((15, ty + 16), artist, fill=MUTED_COLOR, font=fonts['status'])

    draw.text((160, 440), now.strftime('%H:%M'), fill=MUTED_COLOR, font=fonts['time_large'], anchor='mm')

    return img


def draw_playing_screen(track_info, art_canvas, tint_color, accent_color, fonts,
                        progress_now_ms, is_liked, scroll_states):
    img = Image.new('RGB', (SCREEN_WIDTH, SCREEN_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    if art_canvas is not None:
        img.paste(art_canvas, (0, 0))

    for y in range(TRACK_INFO_Y, TRACK_INFO_Y + TRACK_INFO_HEIGHT):
        draw.line([(0, y), (SCREEN_WIDTH, y)], fill=tint_color)

    info_left = 15
    if is_liked:
        hx = SCREEN_WIDTH - 22
        hy = TRACK_INFO_Y + 16
        r = 5
        draw.ellipse([(hx - r, hy - r), (hx, hy + 1)], fill=LIKED_COLOR)
        draw.ellipse([(hx, hy - r), (hx + r, hy + 1)], fill=LIKED_COLOR)
        draw.polygon([(hx - r, hy), (hx + r, hy), (hx, hy + r + 2)], fill=LIKED_COLOR)
        text_right_margin = 40
    else:
        text_right_margin = 20

    max_text_width = SCREEN_WIDTH - info_left - text_right_margin

    track_name = track_info['track_name']
    track_scroll = scroll_states['track']
    if font_getlength(track_name, fonts['track']) > max_text_width:
        draw_scrolling_text(img, draw, info_left, TRACK_INFO_Y + 8, track_name,
                            fonts['track'], TEXT_COLOR, max_text_width, track_scroll.update(), tint_color)
    else:
        draw.text((info_left, TRACK_INFO_Y + 8), track_name, fill=TEXT_COLOR, font=fonts['track'])

    artists = track_info['artists']
    artist_scroll = scroll_states['artist']
    if font_getlength(artists, fonts['artist']) > max_text_width:
        draw_scrolling_text(img, draw, info_left, TRACK_INFO_Y + 36, artists,
                            fonts['artist'], ARTIST_COLOR, max_text_width, artist_scroll.update(), tint_color)
    else:
        draw.text((info_left, TRACK_INFO_Y + 36), artists, fill=ARTIST_COLOR, font=fonts['artist'])

    album_text = track_info['album_name']
    if track_info.get('release_year'):
        album_text = f"{album_text} ({track_info['release_year']})"
    album_text = truncate_text(album_text, fonts['album'], max_text_width)
    draw.text((info_left, TRACK_INFO_Y + 62), album_text, fill=ALBUM_COLOR, font=fonts['album'])

    draw.rectangle([(0, PROGRESS_Y), (SCREEN_WIDTH, PROGRESS_Y + PROGRESS_HEIGHT)], fill=BG_COLOR)

    duration_ms = track_info['duration_ms']
    if duration_ms > 0:
        progress_frac = min(1.0, max(0.0, progress_now_ms / duration_ms))
    else:
        progress_frac = 0

    bar_x_start = 55
    bar_x_end = SCREEN_WIDTH - 55
    bar_y = PROGRESS_Y + 14
    bar_height = 5
    bar_width = bar_x_end - bar_x_start

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
    dot_x = filled_end
    dot_r = 5
    draw.ellipse(
        [(dot_x - dot_r, bar_y + bar_height // 2 - dot_r),
         (dot_x + dot_r, bar_y + bar_height // 2 + dot_r)],
        fill=bar_color,
    )

    elapsed = format_ms(progress_now_ms)
    total = format_ms(duration_ms)
    draw.text((bar_x_start - 5, bar_y + 2), elapsed, fill=PROGRESS_TIME_COLOR, font=fonts['time_small'], anchor='rm')
    draw.text((bar_x_end + 5, bar_y + 2), total, fill=PROGRESS_TIME_COLOR, font=fonts['time_small'], anchor='lm')

    if not track_info['is_playing']:
        pause_y = bar_y - 12
        draw.text((160, pause_y), "PAUSED", fill=MUTED_COLOR, font=fonts['status'], anchor='mm')

    draw.rectangle([(0, STATUS_Y), (SCREEN_WIDTH, SCREEN_HEIGHT)], fill=STATUS_BG)

    status_y_center = STATUS_Y + STATUS_HEIGHT // 2

    shuffle_color = bar_color if track_info['shuffle'] else MUTED_COLOR
    draw.text((15, status_y_center), "SHF", fill=shuffle_color, font=fonts['status'], anchor='lm')

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

    device = truncate_text(track_info['device_name'], fonts['status'], 130)
    draw.text((160, status_y_center), device, fill=ALBUM_COLOR, font=fonts['status'], anchor='mm')

    if track_info['volume'] is not None:
        vol_text = f"VOL {track_info['volume']}%"
        draw.text((SCREEN_WIDTH - 15, status_y_center), vol_text, fill=ALBUM_COLOR, font=fonts['status'], anchor='rm')

    return img


class SpotifyApp(DisplayApp):
    name = 'spotify'

    def __init__(self, ctx):
        super().__init__(ctx)
        self.update_interval = float(self.config.get('poll_interval', 3))
        self.dim_brightness = self.config.get('dim_brightness', 10)
        self.dim_after = self.config.get('dim_after', 300)

        f = self.fonts.font
        # The original used Roboto Light/Medium weights; the shared FontLoader
        # only exposes Regular/Bold, so map to the nearest available weight.
        self._fonts = {
            'track': f('roboto-bold', 22),
            'artist': f('roboto', 18),
            'album': f('roboto', 15),
            'time_small': f('roboto-mono', 11),
            'time_large': f('roboto-mono-bold', 36),
            'status': f('roboto', 12),
            'small': f('roboto', 14),
        }

        # Spotify auth (lazy: no network until the first API call). Reuse the
        # existing token cache so we don't need to re-authenticate.
        cache_path = os.path.join(ROOT_DIR, 'apps', 'spotify', '.spotify_token_cache')
        auth_manager = SpotifyOAuth(
            client_id=self.config['client_id'],
            client_secret=self.config['client_secret'],
            redirect_uri=self.config.get('redirect_uri', 'http://127.0.0.1:8888/callback'),
            scope=SPOTIFY_SCOPE,
            cache_path=cache_path,
            open_browser=False,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)

        # Playback / render state (guarded by self.lock)
        self.current_track_id = None
        self.art_canvas = None
        self.tint_color = BG_COLOR
        self.accent_color = SPOTIFY_GREEN
        self.last_track_info = None
        self.last_api_progress_ms = 0
        self.last_api_time = 0
        self.is_playing = False
        self.is_liked = False
        self.recently_played = None
        self.last_recent_fetch = 0
        self.last_playing_time = time_module.time()
        self.scroll_states = {'track': ScrollState(), 'artist': ScrollState()}

        # Dim state machine (only mutated from render(), which is visible-only)
        self.is_dimmed = False

    @property
    def render_interval(self):
        # Fast frames while playing (smooth scroll + progress), slower when idle.
        return 0.15 if self.is_playing else 0.5

    def update(self):
        current_time = time_module.time()
        playback = get_playback_state(self.sp)
        track_info = extract_track_info(playback)

        if track_info is not None:
            new_art = None
            new_tint = self.tint_color
            new_accent = self.accent_color
            new_liked = self.is_liked
            track_changed = track_info['track_id'] != self.current_track_id
            if track_changed:
                print(f"Now playing: {track_info['track_name']} - {track_info['artists']}")
                raw_art = download_art(track_info['art_url'])
                new_art = prepare_art(raw_art)
                if raw_art is not None:
                    new_tint = get_dominant_color(raw_art)
                    new_accent = get_accent_color(raw_art)
                else:
                    new_tint = BG_COLOR
                    new_accent = SPOTIFY_GREEN
                new_liked = check_liked(self.sp, track_info['track_id'])

            with self.lock:
                self.last_track_info = track_info
                self.is_playing = track_info['is_playing']
                self.last_api_progress_ms = track_info['progress_ms']
                self.last_api_time = current_time
                if self.is_playing:
                    self.last_playing_time = current_time
                if track_changed:
                    self.current_track_id = track_info['track_id']
                    self.art_canvas = new_art
                    self.tint_color = new_tint
                    self.accent_color = new_accent
                    self.is_liked = new_liked
                    max_text_width = SCREEN_WIDTH - 15 - (40 if new_liked else 20)
                    self.scroll_states['track'].reset(track_info['track_name'], self._fonts['track'], max_text_width)
                    self.scroll_states['artist'].reset(track_info['artists'], self._fonts['artist'], max_text_width)
        else:
            with self.lock:
                self.is_playing = False
            # Refresh recently-played when idle (every 30s).
            if current_time - self.last_recent_fetch > 30:
                self.last_recent_fetch = current_time
                recent = get_recently_played(self.sp)
                with self.lock:
                    self.recently_played = recent

    def _apply_dim(self):
        """Auto-dim after a pause; un-dim on resume. Visible-only."""
        now = time_module.time()
        if self.is_playing and self.is_dimmed:
            self.ctx.set_brightness(self.ctx.display.configured_brightness)
            self.is_dimmed = False
        elif (not self.is_playing and not self.is_dimmed
              and now - self.last_playing_time > self.dim_after):
            self.ctx.set_brightness(self.dim_brightness)
            self.is_dimmed = True

    def render(self, now):
        with self.lock:
            self._apply_dim()

            if self.last_track_info is not None and self.is_playing:
                elapsed_since_poll = (time_module.time() - self.last_api_time) * 1000
                progress_now_ms = min(
                    self.last_api_progress_ms + elapsed_since_poll,
                    self.last_track_info['duration_ms'],
                )
            elif self.last_track_info is not None:
                progress_now_ms = self.last_api_progress_ms
            else:
                progress_now_ms = 0

            if self.last_track_info is not None:
                return draw_playing_screen(
                    self.last_track_info, self.art_canvas, self.tint_color,
                    self.accent_color, self._fonts, progress_now_ms,
                    self.is_liked, self.scroll_states,
                )
            return draw_idle_screen(now, self._fonts, self.recently_played)

    def on_hide(self):
        # Restore brightness so the next app isn't left dimmed.
        if self.is_dimmed:
            self.ctx.set_brightness(self.ctx.display.configured_brightness)
            self.is_dimmed = False
