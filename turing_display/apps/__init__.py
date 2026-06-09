"""App registry.

Each app is loaded defensively: a missing optional dependency (e.g. spotipy)
only disables that one app rather than breaking the whole runner.
"""

import importlib

REGISTRY = {}

# name -> (module under turing_display.apps, class name)
_APPS = [
    ('sysmonitor', 'sysmonitor', 'SysmonitorApp'),
    ('weather', 'weather', 'WeatherApp'),
    ('calendar', 'calendar', 'CalendarApp'),
    ('spotify', 'spotify', 'SpotifyApp'),
    ('claude_usage', 'claude_usage', 'ClaudeUsageApp'),
]

for _name, _module, _cls in _APPS:
    try:
        _mod = importlib.import_module(f'turing_display.apps.{_module}')
        REGISTRY[_name] = getattr(_mod, _cls)
    except Exception as e:  # noqa: BLE001 - keep other apps loadable
        print(f"[apps] could not load '{_name}': {e}")
