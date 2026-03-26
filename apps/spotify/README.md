# Spotify Now-Playing Display

Displays the currently playing Spotify track on a Turing 3.5" smart screen (320x480, portrait).

## Features

- Album art (scaled, centered, with dark gradient fade)
- Track name, artist, and album info
- Live progress bar with elapsed/total time (Spotify green)
- Shuffle, repeat, device name, and volume indicators
- Dominant color extraction from album art for subtle background tint
- Idle screen when nothing is playing
- Album art caching to avoid redundant downloads
- Smooth progress bar interpolation between API polls

## Setup

1. Create a Spotify app at https://developer.spotify.com/dashboard
2. Add `http://127.0.0.1:8888/callback` as a Redirect URI in your app settings
3. Copy `config.example.yaml` to `config.yaml` and fill in your `client_id` and `client_secret`
4. Install dependencies: `pip install spotipy requests`
5. Run:

```bash
cd /home/zack/Source/turing-display-apps
source venv/bin/activate
python apps/spotify/spotify_display.py
```

On first run, a browser window will open for Spotify OAuth authorization. After granting access, the token is cached in `apps/spotify/.spotify_token_cache` and reused on subsequent runs.

## Layout

```
+------------------+
|                  |
|   Album Art      |  0-300px
|   (320x300)      |
|     gradient ->  |
+------------------+
| Track Name       |  305-390px
| Artist Name      |
| Album Name       |
+------------------+
| 1:23 [====..] 4:01 | 395-430px
+------------------+
| SHF RPT  Device VOL | 435-480px
+------------------+
```
