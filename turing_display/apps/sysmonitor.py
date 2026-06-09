"""System monitor app (ported from apps/sysmonitor/sysmonitor_display.py).

Data fetching (network/disk speed deltas, GPU poll) happens in ``update()``;
the screen is drawn from psutil + the cached metrics in ``render()``.
"""

import socket
import subprocess
import time as time_module
from datetime import datetime
from types import SimpleNamespace

import psutil
from PIL import Image, ImageDraw

from turing_display import SCREEN_WIDTH, SCREEN_HEIGHT
from turing_display.app_base import DisplayApp

WIDTH = SCREEN_WIDTH
HEIGHT = SCREEN_HEIGHT

# Colors
BG_COLOR = (20, 25, 35)
TEXT_COLOR = (255, 255, 255)
HEADER_COLOR = (100, 200, 255)
MUTED_COLOR = (140, 150, 170)
LABEL_COLOR = (180, 190, 210)
LINE_COLOR = (40, 50, 65)
BAR_BG = (35, 40, 55)
BAR_BORDER = (50, 60, 80)
GREEN = (50, 200, 80)
YELLOW = (230, 190, 40)
RED = (220, 60, 60)


def usage_color(pct):
    if pct < 60:
        return GREEN
    elif pct < 85:
        return YELLOW
    return RED


def temp_color(temp_c):
    if temp_c < 60:
        return GREEN
    elif temp_c < 80:
        return YELLOW
    return RED


def format_bytes(b, suffix='B'):
    for unit in ['', 'K', 'M', 'G', 'T']:
        if abs(b) < 1024:
            return f'{b:.1f}{unit}{suffix}'
        b /= 1024
    return f'{b:.1f}P{suffix}'


def format_speed(bps):
    if bps < 1024:
        return f'{bps:.0f} B/s'
    elif bps < 1024 * 1024:
        return f'{bps / 1024:.1f} KB/s'
    elif bps < 1024 * 1024 * 1024:
        return f'{bps / (1024 * 1024):.1f} MB/s'
    return f'{bps / (1024 * 1024 * 1024):.1f} GB/s'


def format_uptime():
    boot = datetime.fromtimestamp(psutil.boot_time())
    delta = datetime.now() - boot
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes = rem // 60
    parts = []
    if days > 0:
        parts.append(f'{days}d')
    parts.append(f'{hours}h')
    parts.append(f'{minutes:02d}m')
    return 'Up ' + ' '.join(parts)


def get_cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
        for name in ['k10temp', 'coretemp', 'zenpower', 'cpu_thermal', 'acpitz']:
            if name in temps:
                readings = temps[name]
                if readings:
                    current_temps = [r.current for r in readings if r.current > 0]
                    if current_temps:
                        return current_temps[0]
        for name, readings in temps.items():
            for r in readings:
                if r.current > 0:
                    return r.current
    except Exception:
        pass
    return None


def get_active_interface(net_interface):
    if net_interface != 'auto':
        addrs = psutil.net_if_addrs().get(net_interface, [])
        for addr in addrs:
            if addr.family == 2:  # AF_INET
                return net_interface, addr.address
        return net_interface, 'N/A'

    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    for iface, stat in stats.items():
        if stat.isup and iface != 'lo' and not iface.startswith('veth') and not iface.startswith('docker') and not iface.startswith('br-'):
            for addr in addrs.get(iface, []):
                if addr.family == 2:  # AF_INET
                    return iface, addr.address
    return 'N/A', 'N/A'


def get_zfs_pool_usage(pool_name):
    try:
        result = subprocess.run(
            ['zpool', 'list', '-Hp', '-o', 'size,alloc,free', pool_name],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split('\t')
            if len(parts) >= 3:
                total = int(parts[0])
                used = int(parts[1])
                return used, total
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def get_gpu_info():
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(',')
            if len(parts) >= 4:
                return {
                    'usage': int(parts[0].strip()),
                    'temp': int(parts[1].strip()),
                    'vram_used': int(parts[2].strip()),
                    'vram_total': int(parts[3].strip()),
                }
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def draw_bar(draw, x, y, width, height, pct, color=None):
    if color is None:
        color = usage_color(pct)
    draw.rectangle([(x, y), (x + width, y + height)], fill=BAR_BG, outline=BAR_BORDER)
    fill_width = max(0, int((width - 2) * pct / 100))
    if fill_width > 0:
        draw.rectangle([(x + 1, y + 1), (x + 1 + fill_width, y + height - 1)], fill=color)


def draw_cpu_graph(draw, x, y, width, height, history):
    draw.rectangle([(x, y), (x + width, y + height)], fill=BAR_BG)

    num_points = len(history)
    if num_points < 2:
        return

    step = width / (num_points - 1)

    points = []
    for i, val in enumerate(history):
        px = x + int(i * step)
        frac = min(1.0, val / 100.0)
        py = y + height - int(frac * (height - 2)) - 1
        points.append((px, py))

    if len(points) >= 2:
        fill_points = list(points) + [(x + width, y + height), (x, y + height)]
        draw.polygon(fill_points, fill=(30, 60, 40))
        draw.line(points, fill=GREEN, width=1)

    for pct in [25, 50, 75]:
        gy = y + height - int(pct / 100 * (height - 2)) - 1
        for gx in range(x, x + width, 4):
            draw.point((gx, gy), fill=LINE_COLOR)


def draw_net_graph(draw, x, y, width, height, down_history, up_history):
    draw.rectangle([(x, y), (x + width, y + height)], fill=BAR_BG)

    all_vals = down_history + up_history
    peak = max(max(all_vals), 1024)

    num_points = len(down_history)
    if num_points < 2:
        return

    step = width / (num_points - 1)

    for history, color in [(up_history, (180, 160, 30)), (down_history, (40, 160, 80))]:
        points = []
        for i, val in enumerate(history):
            px = x + int(i * step)
            frac = min(1.0, val / peak)
            py = y + height - int(frac * (height - 2)) - 1
            points.append((px, py))
        if len(points) >= 2:
            draw.line(points, fill=color, width=1)

    mid_y = y + height // 2
    for gx in range(x, x + width, 4):
        draw.point((gx, mid_y), fill=LINE_COLOR)


def draw_mini_bars(draw, x, y, width, height, percentages):
    count = len(percentages)
    if count == 0:
        return
    gap = 1
    bar_w = max(1, (width - (count - 1) * gap) // count)
    for i, pct in enumerate(percentages):
        bx = x + i * (bar_w + gap)
        color = usage_color(pct)
        draw.rectangle([(bx, y), (bx + bar_w, y + height)], fill=BAR_BG)
        fill_h = max(0, int(height * pct / 100))
        if fill_h > 0:
            draw.rectangle([(bx, y + height - fill_h), (bx + bar_w, y + height)], fill=color)


def draw_gradient(draw, y_start, y_end):
    for y in range(y_start, y_end):
        progress = y / y_end
        r = int(30 + 10 * (1 - progress))
        g = int(40 + 15 * (1 - progress))
        b = int(60 + 15 * (1 - progress))
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def draw_section_header(draw, y, title, fonts):
    y += 6  # padding above divider
    draw.line([(10, y), (310, y)], fill=LINE_COLOR, width=1)
    draw.text((10, y + 6), title, fill=HEADER_COLOR, font=fonts['section'], anchor='lt')
    return y + 22  # padding below title


def truncate_text(text, font, max_width):
    if font.getlength(text) <= max_width:
        return text
    while font.getlength(text + '...') > max_width and len(text) > 0:
        text = text[:-1]
    return text + '...' if text else ''


class SystemMetrics:
    """Collects and caches system metrics."""

    HISTORY_LEN = 60  # 60 samples of history

    def __init__(self, show_gpu=True):
        self.show_gpu = show_gpu
        self.prev_net_io = psutil.net_io_counters()
        self.prev_disk_io = psutil.disk_io_counters()
        self.prev_time = time_module.time()
        self.net_up_speed = 0.0
        self.net_down_speed = 0.0
        self.net_down_history = [0.0] * self.HISTORY_LEN
        self.net_up_history = [0.0] * self.HISTORY_LEN
        self.cpu_history = [0.0] * self.HISTORY_LEN
        self.disk_read_speed = 0.0
        self.disk_write_speed = 0.0
        self.gpu_info = None
        self.gpu_check_interval = 5
        self.gpu_last_check = 0
        self.gpu_available = None  # None = unknown, True/False after first check

    def update(self):
        now = time_module.time()
        dt = now - self.prev_time
        if dt < 0.1:
            return
        self.prev_time = now

        net_io = psutil.net_io_counters()
        self.net_down_speed = (net_io.bytes_recv - self.prev_net_io.bytes_recv) / dt
        self.net_up_speed = (net_io.bytes_sent - self.prev_net_io.bytes_sent) / dt
        self.prev_net_io = net_io
        self.net_down_history.append(self.net_down_speed)
        self.net_down_history = self.net_down_history[-self.HISTORY_LEN:]
        self.net_up_history.append(self.net_up_speed)
        self.net_up_history = self.net_up_history[-self.HISTORY_LEN:]
        self.cpu_history.append(psutil.cpu_percent(interval=0))
        self.cpu_history = self.cpu_history[-self.HISTORY_LEN:]

        try:
            disk_io = psutil.disk_io_counters()
            if disk_io and self.prev_disk_io:
                self.disk_read_speed = (disk_io.read_bytes - self.prev_disk_io.read_bytes) / dt
                self.disk_write_speed = (disk_io.write_bytes - self.prev_disk_io.write_bytes) / dt
            self.prev_disk_io = disk_io
        except Exception:
            pass

        if self.show_gpu and (self.gpu_available is None or self.gpu_available):
            if now - self.gpu_last_check >= self.gpu_check_interval:
                self.gpu_last_check = now
                self.gpu_info = get_gpu_info()
                if self.gpu_available is None:
                    self.gpu_available = self.gpu_info is not None


def draw_screen(now, metrics, fonts, cfg):
    """Draw the complete system monitor screen."""
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    L = 10   # left margin
    R = 310  # right margin

    y = 0

    # === HEADER SECTION ===
    header_h = 56
    draw_gradient(draw, 0, header_h)

    hostname = socket.gethostname()
    uptime_str = format_uptime()
    time_str = now.strftime('%H:%M:%S')

    draw.text((L, 6), hostname, fill=TEXT_COLOR, font=fonts['bold'], anchor='lt')
    draw.text((R, 6), time_str, fill=HEADER_COLOR, font=fonts['mono_med'], anchor='rt')
    draw.text((160, 32), uptime_str, fill=MUTED_COLOR, font=fonts['small'], anchor='mt')

    y = header_h

    # === CPU SECTION ===
    if cfg.show_cpu:
        draw.text((L, y + 6), 'CPU', fill=HEADER_COLOR, font=fonts['section'], anchor='lt')
        y += 22

        cpu_pct = psutil.cpu_percent(interval=0)
        per_core = psutil.cpu_percent(interval=0, percpu=True)
        per_core_freq = psutil.cpu_freq(percpu=True)
        if per_core_freq:
            freqs = [f.current for f in per_core_freq]
            freq_min = min(freqs)
            freq_avg = sum(freqs) / len(freqs)
            freq_max = max(freqs)
        else:
            freq = psutil.cpu_freq()
            freq_min = freq_avg = freq_max = freq.current if freq else None
        cpu_temp = get_cpu_temp()

        pct_text = f'{cpu_pct:.0f}%'
        draw.text((L, y), pct_text, fill=usage_color(cpu_pct), font=fonts['big_mono'], anchor='lt')
        pct_w = int(fonts['big_mono'].getlength(pct_text))
        if cpu_temp is not None:
            draw.text((L + pct_w + 8, y + 4), f'{cpu_temp:.0f}°C', fill=temp_color(cpu_temp), font=fonts['tiny'], anchor='lt')

        graph_x = max(95, L + pct_w + 50)
        draw_cpu_graph(draw, graph_x, y, R - graph_x, 22, metrics.cpu_history)

        info_y = y + 26
        if freq_max is not None:
            freq_text = f'{freq_min:.0f} / {freq_avg:.0f} / {freq_max:.0f} MHz'
            draw.text((L, info_y), freq_text, fill=LABEL_COLOR, font=fonts['tiny'], anchor='lt')

        core_y = info_y + 14
        draw_mini_bars(draw, L, core_y, R - L, 12, per_core)

        y = core_y + 14

    # === MEMORY SECTION ===
    if cfg.show_memory:
        y = draw_section_header(draw, y, 'MEMORY', fonts)

        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        mem_used = mem.used / (1024 ** 3)
        mem_total = mem.total / (1024 ** 3)

        draw_bar(draw, L, y + 2, 200, 12, mem_pct)
        draw.text((215, y + 2), f'{mem_pct:.0f}%', fill=usage_color(mem_pct), font=fonts['small'], anchor='lt')
        mem_text = f'{mem_used:.1f}/{mem_total:.1f} GB'
        draw.text((R, y + 2), mem_text, fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')

        y += 18

        swap = psutil.swap_memory()
        if swap.total > 0:
            swap_pct = swap.percent
            swap_used = swap.used / (1024 ** 3)
            swap_total = swap.total / (1024 ** 3)
            draw.text((L, y), 'Swap', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
            draw_bar(draw, 45, y + 1, 115, 10, swap_pct)
            draw.text((R, y), f'{swap_used:.1f}/{swap_total:.1f} GB', fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')
            y += 12

    # === DISK SECTION ===
    if cfg.show_disk:
        y = draw_section_header(draw, y, 'DISK', fonts)

        try:
            if cfg.zfs_pool:
                zfs = get_zfs_pool_usage(cfg.zfs_pool)
                if zfs:
                    disk_used = zfs[0] / (1024 ** 3)
                    disk_total = zfs[1] / (1024 ** 3)
                    disk_pct = (zfs[0] / zfs[1] * 100) if zfs[1] > 0 else 0
                else:
                    disk = psutil.disk_usage(cfg.disk_mount)
                    disk_pct, disk_used, disk_total = disk.percent, disk.used / (1024 ** 3), disk.total / (1024 ** 3)
            else:
                disk = psutil.disk_usage(cfg.disk_mount)
                disk_pct, disk_used, disk_total = disk.percent, disk.used / (1024 ** 3), disk.total / (1024 ** 3)

            if disk_total >= 1024:
                size_text = f'{disk_used / 1024:.1f}/{disk_total / 1024:.1f} TB'
            else:
                size_text = f'{disk_used:.0f}/{disk_total:.0f} GB'

            draw_bar(draw, L, y + 2, 200, 12, disk_pct)
            draw.text((215, y + 2), f'{disk_pct:.0f}%', fill=usage_color(disk_pct), font=fonts['small'], anchor='lt')
            draw.text((R, y + 2), size_text, fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')

            y += 18

            draw.text((L, y), f'R: {format_speed(metrics.disk_read_speed)}', fill=GREEN, font=fonts['tiny'], anchor='lt')
            draw.text((R, y), f'W: {format_speed(metrics.disk_write_speed)}', fill=YELLOW, font=fonts['tiny'], anchor='rt')
            y += 12
        except OSError:
            draw.text((L, y + 2), f'Mount {cfg.disk_mount} unavailable', fill=RED, font=fonts['tiny'], anchor='lt')
            y += 14

    # === NETWORK SECTION ===
    if cfg.show_network:
        y = draw_section_header(draw, y, 'NETWORK', fonts)

        iface, ip_addr = get_active_interface(cfg.net_interface)

        draw.text((L, y), iface, fill=LABEL_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((R, y), ip_addr, fill=MUTED_COLOR, font=fonts['tiny'], anchor='rt')
        y += 15

        draw.text((L, y), f'▼ {format_speed(metrics.net_down_speed)}', fill=GREEN, font=fonts['small'], anchor='lt')
        draw.text((R, y), f'▲ {format_speed(metrics.net_up_speed)}', fill=YELLOW, font=fonts['small'], anchor='rt')
        y += 19

        draw_net_graph(draw, L, y, R - L, 36, metrics.net_down_history, metrics.net_up_history)
        y += 40

        net_io = psutil.net_io_counters()
        draw.text((L, y), f'Rx: {format_bytes(net_io.bytes_recv)}', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((R, y), f'Tx: {format_bytes(net_io.bytes_sent)}', fill=MUTED_COLOR, font=fonts['tiny'], anchor='rt')
        y += 12

    # === GPU SECTION ===
    if cfg.show_gpu and metrics.gpu_available:
        gpu = metrics.gpu_info
        if gpu:
            y = draw_section_header(draw, y, 'GPU', fonts)

            gpu_pct = gpu['usage']
            draw_bar(draw, L, y + 2, 140, 12, gpu_pct)
            draw.text((155, y + 2), f'{gpu_pct}%', fill=usage_color(gpu_pct), font=fonts['small'], anchor='lt')
            gpu_temp = gpu['temp']
            draw.text((R, y + 2), f'{gpu_temp}°C', fill=temp_color(gpu_temp), font=fonts['small'], anchor='rt')
            y += 18

            vram_pct = (gpu['vram_used'] / gpu['vram_total'] * 100) if gpu['vram_total'] > 0 else 0
            draw.text((L, y), 'VRAM', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
            draw_bar(draw, 45, y + 1, 120, 10, vram_pct)
            draw.text((R, y), f'{gpu["vram_used"]}/{gpu["vram_total"]} MB', fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')
            y += 12

    # === TOP PROCESSES SECTION ===
    if cfg.show_processes:
        y = draw_section_header(draw, y, 'TOP PROCESSES', fonts)

        try:
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = p.info
                    if info['cpu_percent'] is not None and info['pid'] != 0:
                        procs.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            procs.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)

            remaining_h = HEIGHT - y - 8
            row_h = 16
            max_procs = min(5, max(1, remaining_h // row_h))

            for proc in procs[:max_procs]:
                pid = proc['pid']
                name = proc['name'] or 'unknown'
                cpu = proc['cpu_percent'] or 0
                mem = proc['memory_percent'] or 0

                name = truncate_text(name, fonts['tiny'], 120)

                draw.text((L, y), f'{pid}', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
                draw.text((50, y), name, fill=LABEL_COLOR, font=fonts['tiny'], anchor='lt')
                draw.text((220, y), f'{cpu:5.1f}%', fill=usage_color(min(cpu, 100)), font=fonts['tiny_mono'], anchor='lt')
                draw.text((R, y), f'{mem:.1f}%', fill=MUTED_COLOR, font=fonts['tiny_mono'], anchor='rt')
                y += row_h
        except Exception:
            draw.text((L, y), 'Error reading processes', fill=RED, font=fonts['tiny'], anchor='lt')

    return img


class SysmonitorApp(DisplayApp):
    name = 'sysmonitor'

    def __init__(self, ctx):
        super().__init__(ctx)
        sections = self.config.get('sections', {}) or {}
        disk = self.config.get('disk', {}) or {}
        network = self.config.get('network', {}) or {}
        self.cfg = SimpleNamespace(
            show_cpu=sections.get('cpu', True),
            show_memory=sections.get('memory', True),
            show_disk=sections.get('disk', True),
            show_network=sections.get('network', True),
            show_gpu=sections.get('gpu', True),
            show_processes=sections.get('processes', True),
            disk_mount=disk.get('mount_point', '/'),
            zfs_pool=disk.get('zfs_pool', ''),
            net_interface=network.get('interface', 'auto'),
        )
        # Refresh cadence: how often delta-based metrics are recomputed.
        self.update_interval = float(self.config.get('refresh_rate', 1.0))
        self.render_interval = self.update_interval

        f = self.fonts.font
        self._fonts = {
            'bold': f('roboto-bold', 20),
            'mono_med': f('roboto-mono-bold', 20),
            'big_mono': f('roboto-mono-bold', 24),
            'section': f('roboto-bold', 12),
            'small': f('roboto', 14),
            'tiny': f('roboto', 11),
            'tiny_mono': f('roboto-mono', 11),
        }

        # Prime psutil percent counters (first call returns 0).
        psutil.cpu_percent(interval=0)
        psutil.cpu_percent(interval=0, percpu=True)
        self.metrics = SystemMetrics(show_gpu=self.cfg.show_gpu)

    def update(self):
        with self.lock:
            self.metrics.update()

    def render(self, now):
        with self.lock:
            return draw_screen(now, self.metrics, self._fonts, self.cfg)
