"""Background data-update scheduler.

Decides which apps should have ``update()`` called and when:
  * the active app polls on its own ``update_interval``;
  * a hidden app polls only if its ``keep_warm`` flag is set;
  * a switch can ``force()`` an immediate refresh of the newly-active app.

Updates run on a thread pool so a slow fetch (e.g. CalDAV) never blocks the
render loop or other apps. An optional ``on_update`` callback fires after each
successful update so the runner can re-render immediately when fresh data
arrives.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor


class UpdateScheduler:
    def __init__(self, apps, is_active, on_update=None, tick=0.2, max_workers=4):
        self.apps = apps
        self.is_active = is_active
        self.on_update = on_update
        self.tick = tick
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # monotonic timestamp each app is next due; 0.0 == due immediately.
        self._next_due = {app.name: 0.0 for app in apps}
        self._inflight = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name='turing-scheduler', daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._executor.shutdown(wait=False)

    def force(self, app_name):
        """Mark an app due immediately (used when it becomes active)."""
        with self._lock:
            self._next_due[app_name] = 0.0

    def _run_update(self, app):
        ok = False
        try:
            app.update()
            ok = True
        except Exception as e:
            print(f"[scheduler] {app.name}.update() failed: {e}")
        finally:
            with self._lock:
                self._inflight.discard(app.name)
                self._next_due[app.name] = time.monotonic() + app.update_interval
        if ok and self.on_update is not None:
            try:
                self.on_update(app)
            except Exception as e:
                print(f"[scheduler] on_update callback failed: {e}")

    def _loop(self):
        while not self._stop.is_set():
            now = time.monotonic()
            for app in self.apps:
                if not (self.is_active(app) or app.keep_warm):
                    continue
                with self._lock:
                    if app.name in self._inflight:
                        continue
                    if now < self._next_due[app.name]:
                        continue
                    self._inflight.add(app.name)
                self._executor.submit(self._run_update, app)
            self._stop.wait(self.tick)
