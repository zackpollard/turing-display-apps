"""Control plane: a Unix-domain-socket server and a tiny client helper.

The runner runs a ``ControlServer`` in a daemon thread. ``turing-ctl`` (and any
other process) uses ``send_command()`` to issue one-line commands such as
``next``, ``prev``, ``switch <app>``, ``current``, ``list`` and ``status``.
"""

import os
import socket
import threading


def default_socket_path():
    runtime = os.environ.get('XDG_RUNTIME_DIR') or '/tmp'
    return os.path.join(runtime, 'turing-display.sock')


class ControlServer:
    def __init__(self, path, handler):
        # handler(command: str, args: list[str]) -> str
        self.path = path
        self.handler = handler
        self._sock = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, name='turing-control', daemon=True)

    def start(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(5)
        self._sock.settimeout(0.5)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(4096).decode().strip()
                    parts = data.split()
                    if not parts:
                        reply = 'ERR empty command'
                    else:
                        reply = self.handler(parts[0], parts[1:])
                except Exception as e:
                    reply = f'ERR {e}'
                try:
                    conn.sendall((reply + '\n').encode())
                except OSError:
                    pass

    def stop(self):
        self._stop.set()
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        try:
            os.unlink(self.path)
        except OSError:
            pass


def send_command(path, args):
    """Send a command to a running runner; return its reply string."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(path)
    try:
        s.sendall(' '.join(args).encode())
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            buf = s.recv(65536)
            if not buf:
                break
            chunks.append(buf)
        return b''.join(chunks).decode().strip()
    finally:
        s.close()
