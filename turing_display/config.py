"""Load the unified runner configuration.

A single root ``config.yaml`` holds the display settings, the runner settings
(app order, default app, control socket) and a per-app ``apps:`` section. The
real file is gitignored (it contains credentials); ``config.example.yaml`` is
the committed template.
"""

import os

import yaml

from turing_display import ROOT_DIR

DEFAULT_CONFIG_PATH = os.path.join(ROOT_DIR, 'config.yaml')


def load_config(path=None):
    """Load and return the config dict.

    Resolution order: explicit ``path`` arg, ``$TURING_CONFIG``, then the
    repo-root ``config.yaml``.
    """
    path = path or os.environ.get('TURING_CONFIG') or DEFAULT_CONFIG_PATH
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}
