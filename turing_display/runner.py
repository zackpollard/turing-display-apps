"""The runner: wires display + renderer + apps + scheduler + control together
and drives the main render loop.
"""

import signal
import threading
import time
from datetime import datetime

from turing_display import SCREEN_WIDTH, SCREEN_HEIGHT
from turing_display.app_base import AppContext
from turing_display.apps import REGISTRY
from turing_display.config import load_config
from turing_display.control import ControlServer, default_socket_path
from turing_display.display import Display
from turing_display.fonts import FontLoader
from turing_display.renderer import Renderer
from turing_display.scheduler import UpdateScheduler

BASE_TICK = 0.05  # main-loop poll interval (s)


class Runner:
    def __init__(self, config):
        self.config = config

        disp_cfg = config.get('display', {}) or {}
        self.display = Display(
            com_port=disp_cfg.get('com_port', 'AUTO'),
            brightness=disp_cfg.get('brightness', 50),
        )
        self.renderer = Renderer(self.display)
        self.fonts = FontLoader()

        runner_cfg = config.get('runner', {}) or {}
        order = runner_cfg.get('order') or list(REGISTRY.keys())
        apps_cfg = config.get('apps', {}) or {}

        self.apps = []
        for name in order:
            cls = REGISTRY.get(name)
            if cls is None:
                print(f"[runner] unknown/unavailable app '{name}', skipping")
                continue
            ctx = AppContext(
                fonts=self.fonts,
                config=apps_cfg.get(name, {}) or {},
                display=self.display,
                width=SCREEN_WIDTH,
                height=SCREEN_HEIGHT,
            )
            try:
                self.apps.append(cls(ctx))
            except Exception as e:
                print(f"[runner] failed to init app '{name}': {e}")
        if not self.apps:
            raise SystemExit('No apps could be initialized; check config.')

        self._index_lock = threading.Lock()
        self.active_index = 0
        default_app = runner_cfg.get('default_app')
        if default_app:
            for i, app in enumerate(self.apps):
                if app.name == default_app:
                    self.active_index = i
                    break

        # Set by switches / completed updates to force an immediate re-render.
        self._dirty = threading.Event()
        self._dirty.set()

        self.scheduler = UpdateScheduler(
            self.apps, is_active=self._is_active, on_update=self._on_update)
        self.sock_path = runner_cfg.get('socket_path') or default_socket_path()
        self.control = ControlServer(self.sock_path, self._handle_command)
        self._stop = threading.Event()

    # --- active-app state -------------------------------------------------

    @property
    def active(self):
        with self._index_lock:
            return self.apps[self.active_index]

    def _is_active(self, app):
        return app is self.active

    def _on_update(self, app):
        # Fresh data arrived; if it's for the visible app, redraw now.
        if app is self.active:
            self._dirty.set()

    def _activate(self, idx):
        idx %= len(self.apps)
        with self._index_lock:
            if idx == self.active_index:
                return self.apps[idx]
            old = self.apps[self.active_index]
            self.active_index = idx
            new = self.apps[idx]
        for hook, label in ((old.on_hide, 'on_hide'), (new.on_show, 'on_show')):
            try:
                hook()
            except Exception as e:
                print(f"[runner] {label} failed: {e}")
        self.scheduler.force(new.name)
        self._dirty.set()
        return new

    def step(self, delta):
        with self._index_lock:
            idx = (self.active_index + delta) % len(self.apps)
        return self._activate(idx)

    def switch_to(self, name):
        for i, app in enumerate(self.apps):
            if app.name == name:
                return self._activate(i)
        return None

    # --- control protocol -------------------------------------------------

    def _handle_command(self, cmd, args):
        cmd = cmd.lower()
        if cmd in ('next', 'prev'):
            app = self.step(1 if cmd == 'next' else -1)
            return f'OK {app.name}'
        if cmd in ('switch', 'show'):
            if not args:
                return 'ERR usage: switch <app>'
            app = self.switch_to(args[0])
            return f'OK {app.name}' if app else f"ERR unknown app '{args[0]}'"
        if cmd == 'current':
            return self.active.name
        if cmd == 'list':
            active = self.active
            return ' '.join(
                ('*' + a.name) if a is active else a.name for a in self.apps)
        if cmd == 'status':
            return (f'active={self.active.name} '
                    f"apps={','.join(a.name for a in self.apps)}")
        return f"ERR unknown command '{cmd}'"

    # --- main loop --------------------------------------------------------

    def run(self):
        self.scheduler.start()
        self.control.start()
        signal.signal(signal.SIGTERM, lambda *_: self._stop.set())

        last_app = None
        last_render = 0.0
        print(f'[runner] socket: {self.sock_path}')
        print(f"[runner] apps: {[a.name for a in self.apps]} "
              f'(active: {self.active.name})')
        try:
            while not self._stop.is_set():
                app = self.active
                now_mono = time.monotonic()
                due = (self._dirty.is_set()
                       or app is not last_app
                       or (now_mono - last_render) >= app.render_interval)
                if due:
                    self._dirty.clear()
                    now = datetime.now()
                    # The app guards its own state with self.lock internally;
                    # the runner must not hold it here (locks aren't reentrant).
                    try:
                        frame = app.render(now)
                    except Exception as e:
                        print(f"[runner] {app.name}.render() failed: {e}")
                        frame = None
                    if frame is not None:
                        self.renderer.push(frame)
                        last_render = now_mono
                        last_app = app
                time.sleep(BASE_TICK)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        self._stop.set()
        self.scheduler.stop()
        self.control.stop()
        try:
            self.active.on_hide()
        except Exception:
            pass
        self.display.close()
        print('[runner] stopped.')


def main():
    runner = Runner(load_config())
    runner.run()


if __name__ == '__main__':
    main()
