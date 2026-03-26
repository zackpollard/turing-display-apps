#!/usr/bin/env python3
"""System monitor display for Turing 3.5" screen."""

import sys
import os

# Add the submodule to the path
APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(os.path.dirname(APP_DIR))
sys.path.insert(0, os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen'))

import yaml
import socket
import subprocess
from datetime import datetime, timedelta
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from library.lcd.lcd_comm import Orientation
from PIL import Image, ImageDraw, ImageFont
import time as time_module
import numpy as np
import psutil

# Load configuration
def load_config():
    config_path = os.path.join(APP_DIR, 'config.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# Display settings
COM_PORT = CONFIG['display'].get('com_port', 'AUTO')
BRIGHTNESS = CONFIG['display'].get('brightness', 50)
REFRESH_RATE = CONFIG.get('refresh_rate', 1.0)

# Section toggles
SECTIONS = CONFIG.get('sections', {})
SHOW_CPU = SECTIONS.get('cpu', True)
SHOW_MEMORY = SECTIONS.get('memory', True)
SHOW_DISK = SECTIONS.get('disk', True)
SHOW_NETWORK = SECTIONS.get('network', True)
SHOW_GPU = SECTIONS.get('gpu', True)
SHOW_PROCESSES = SECTIONS.get('processes', True)

# Config values
DISK_MOUNT = CONFIG.get('disk', {}).get('mount_point', '/')
ZFS_POOL = CONFIG.get('disk', {}).get('zfs_pool', '')
NET_INTERFACE = CONFIG.get('network', {}).get('interface', 'auto')

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

# Font paths
FONT_DIR = os.path.join(ROOT_DIR, 'lib', 'turing-smart-screen', 'res', 'fonts')

# Screen dimensions
WIDTH = 320
HEIGHT = 480


def usage_color(pct):
    """Return green/yellow/red based on usage percentage."""
    if pct < 60:
        return GREEN
    elif pct < 85:
        return YELLOW
    return RED


def temp_color(temp_c):
    """Return green/yellow/red based on temperature."""
    if temp_c < 60:
        return GREEN
    elif temp_c < 80:
        return YELLOW
    return RED


def format_bytes(b, suffix='B'):
    """Format bytes to human-readable string."""
    for unit in ['', 'K', 'M', 'G', 'T']:
        if abs(b) < 1024:
            return f'{b:.1f}{unit}{suffix}'
        b /= 1024
    return f'{b:.1f}P{suffix}'


def format_speed(bps):
    """Format bytes per second to human-readable speed."""
    if bps < 1024:
        return f'{bps:.0f} B/s'
    elif bps < 1024 * 1024:
        return f'{bps / 1024:.1f} KB/s'
    elif bps < 1024 * 1024 * 1024:
        return f'{bps / (1024 * 1024):.1f} MB/s'
    return f'{bps / (1024 * 1024 * 1024):.1f} GB/s'


def format_uptime():
    """Format system uptime as a readable string."""
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
    """Get CPU temperature from psutil sensors or hwmon."""
    try:
        temps = psutil.sensors_temperatures()
        # Try common sensor names
        for name in ['k10temp', 'coretemp', 'zenpower', 'cpu_thermal', 'acpitz']:
            if name in temps:
                readings = temps[name]
                if readings:
                    # Average all readings or take the first (Tctl/Tdie for AMD)
                    current_temps = [r.current for r in readings if r.current > 0]
                    if current_temps:
                        return current_temps[0]
        # Fallback: try first available sensor
        for name, readings in temps.items():
            for r in readings:
                if r.current > 0:
                    return r.current
    except Exception:
        pass
    return None


def get_active_interface():
    """Get the active network interface and its IP address."""
    if NET_INTERFACE != 'auto':
        addrs = psutil.net_if_addrs().get(NET_INTERFACE, [])
        for addr in addrs:
            if addr.family == 2:  # AF_INET
                return NET_INTERFACE, addr.address
        return NET_INTERFACE, 'N/A'

    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    for iface, stat in stats.items():
        if stat.isup and iface != 'lo' and not iface.startswith('veth') and not iface.startswith('docker') and not iface.startswith('br-'):
            for addr in addrs.get(iface, []):
                if addr.family == 2:  # AF_INET
                    return iface, addr.address
    return 'N/A', 'N/A'


def get_zfs_pool_usage(pool_name):
    """Get ZFS pool-level usage stats. Returns (used_bytes, total_bytes) or None."""
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
    """Get GPU info via nvidia-smi. Returns dict or None."""
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
    """Draw a usage bar with border and fill."""
    if color is None:
        color = usage_color(pct)
    # Background
    draw.rectangle([(x, y), (x + width, y + height)], fill=BAR_BG, outline=BAR_BORDER)
    # Fill
    fill_width = max(0, int((width - 2) * pct / 100))
    if fill_width > 0:
        draw.rectangle([(x + 1, y + 1), (x + 1 + fill_width, y + height - 1)], fill=color)


def draw_cpu_graph(draw, x, y, width, height, history):
    """Draw a CPU usage line graph (0-100%)."""
    draw.rectangle([(x, y), (x + width, y + height)], fill=BAR_BG)

    num_points = len(history)
    if num_points < 2:
        return

    step = width / (num_points - 1)

    # Filled area under the line
    points = []
    for i, val in enumerate(history):
        px = x + int(i * step)
        frac = min(1.0, val / 100.0)
        py = y + height - int(frac * (height - 2)) - 1
        points.append((px, py))

    # Draw filled polygon
    if len(points) >= 2:
        fill_points = list(points) + [(x + width, y + height), (x, y + height)]
        draw.polygon(fill_points, fill=(30, 60, 40))
        draw.line(points, fill=GREEN, width=1)

    # Grid lines at 25%, 50%, 75%
    for pct in [25, 50, 75]:
        gy = y + height - int(pct / 100 * (height - 2)) - 1
        for gx in range(x, x + width, 4):
            draw.point((gx, gy), fill=LINE_COLOR)


def draw_net_graph(draw, x, y, width, height, down_history, up_history):
    """Draw a network speed graph with download and upload lines."""
    # Background
    draw.rectangle([(x, y), (x + width, y + height)], fill=BAR_BG)

    # Find the max value for scaling (at least 1 KB/s to avoid division by zero)
    all_vals = down_history + up_history
    peak = max(max(all_vals), 1024)

    num_points = len(down_history)
    if num_points < 2:
        return

    step = width / (num_points - 1)

    # Draw upload first (behind), then download
    for history, color in [(up_history, (180, 160, 30)), (down_history, (40, 160, 80))]:
        points = []
        for i, val in enumerate(history):
            px = x + int(i * step)
            # Clamp and scale
            frac = min(1.0, val / peak)
            py = y + height - int(frac * (height - 2)) - 1
            points.append((px, py))
        if len(points) >= 2:
            draw.line(points, fill=color, width=1)

    # Subtle grid line at 50%
    mid_y = y + height // 2
    for gx in range(x, x + width, 4):
        draw.point((gx, mid_y), fill=LINE_COLOR)


def draw_mini_bars(draw, x, y, width, height, percentages):
    """Draw compact per-core mini bars side by side."""
    count = len(percentages)
    if count == 0:
        return
    gap = 1
    bar_w = max(1, (width - (count - 1) * gap) // count)
    for i, pct in enumerate(percentages):
        bx = x + i * (bar_w + gap)
        color = usage_color(pct)
        # Background
        draw.rectangle([(bx, y), (bx + bar_w, y + height)], fill=BAR_BG)
        # Fill from bottom up
        fill_h = max(0, int(height * pct / 100))
        if fill_h > 0:
            draw.rectangle([(bx, y + height - fill_h), (bx + bar_w, y + height)], fill=color)


def draw_gradient(draw, y_start, y_end):
    """Draw a gradient background for the header."""
    for y in range(y_start, y_end):
        progress = y / y_end
        r = int(30 + 10 * (1 - progress))
        g = int(40 + 15 * (1 - progress))
        b = int(60 + 15 * (1 - progress))
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def draw_section_header(draw, y, title, fonts):
    """Draw a section header with title."""
    y += 6  # padding above divider
    draw.line([(10, y), (310, y)], fill=LINE_COLOR, width=1)
    draw.text((10, y + 6), title, fill=HEADER_COLOR, font=fonts['section'], anchor='lt')
    return y + 22  # padding below title


def truncate_text(text, font, max_width):
    """Truncate text with ellipsis if it exceeds max_width."""
    if font.getlength(text) <= max_width:
        return text
    while font.getlength(text + '...') > max_width and len(text) > 0:
        text = text[:-1]
    return text + '...' if text else ''


class SystemMetrics:
    """Collects and caches system metrics."""

    HISTORY_LEN = 60  # 60 samples of history

    def __init__(self):
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
        """Update delta-based metrics (network/disk speeds)."""
        now = time_module.time()
        dt = now - self.prev_time
        if dt < 0.1:
            return
        self.prev_time = now

        # Network speeds
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

        # Disk IO speeds
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io and self.prev_disk_io:
                self.disk_read_speed = (disk_io.read_bytes - self.prev_disk_io.read_bytes) / dt
                self.disk_write_speed = (disk_io.write_bytes - self.prev_disk_io.write_bytes) / dt
            self.prev_disk_io = disk_io
        except Exception:
            pass

        # GPU info (less frequent)
        if SHOW_GPU and (self.gpu_available is None or self.gpu_available):
            if now - self.gpu_last_check >= self.gpu_check_interval:
                self.gpu_last_check = now
                self.gpu_info = get_gpu_info()
                if self.gpu_available is None:
                    self.gpu_available = self.gpu_info is not None


def draw_screen(now, metrics, fonts):
    """Draw the complete system monitor screen."""
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Consistent margins: 10px left/right, content area 10-310
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

    # === CPU SECTION (no divider — offsets against header) ===
    if SHOW_CPU:
        draw.text((L, y + 6), 'CPU', fill=HEADER_COLOR, font=fonts['section'], anchor='lt')
        y += 22

        cpu_pct = psutil.cpu_percent(interval=0)
        per_core = psutil.cpu_percent(interval=0, percpu=True)
        # Per-core frequencies: min, avg, max
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

        # CPU percentage large + graph
        pct_text = f'{cpu_pct:.0f}%'
        draw.text((L, y), pct_text, fill=usage_color(cpu_pct), font=fonts['big_mono'], anchor='lt')
        pct_w = int(fonts['big_mono'].getlength(pct_text))
        if cpu_temp is not None:
            draw.text((L + pct_w + 8, y + 4), f'{cpu_temp:.0f}\u00b0C', fill=temp_color(cpu_temp), font=fonts['tiny'], anchor='lt')

        # CPU usage history graph next to percentage
        graph_x = max(95, L + pct_w + 50)
        draw_cpu_graph(draw, graph_x, y, R - graph_x, 22, metrics.cpu_history)

        # Frequency min/avg/max and per-core bars below
        info_y = y + 26
        if freq_max is not None:
            freq_text = f'{freq_min:.0f} / {freq_avg:.0f} / {freq_max:.0f} MHz'
            draw.text((L, info_y), freq_text, fill=LABEL_COLOR, font=fonts['tiny'], anchor='lt')

        # Per-core mini bars
        core_y = info_y + 14
        draw_mini_bars(draw, L, core_y, R - L, 12, per_core)

        y = core_y + 14

    # === MEMORY SECTION ===
    if SHOW_MEMORY:
        y = draw_section_header(draw, y, 'MEMORY', fonts)

        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        mem_used = mem.used / (1024 ** 3)
        mem_total = mem.total / (1024 ** 3)

        # RAM bar + percentage + used/total all on one line
        draw_bar(draw, L, y + 2, 200, 12, mem_pct)
        draw.text((215, y + 2), f'{mem_pct:.0f}%', fill=usage_color(mem_pct), font=fonts['small'], anchor='lt')
        mem_text = f'{mem_used:.1f}/{mem_total:.1f} GB'
        draw.text((R, y + 2), mem_text, fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')

        y += 18

        # Swap
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
    if SHOW_DISK:
        y = draw_section_header(draw, y, 'DISK', fonts)

        try:
            # Use ZFS pool stats if configured, otherwise fall back to psutil
            if ZFS_POOL:
                zfs = get_zfs_pool_usage(ZFS_POOL)
                if zfs:
                    disk_used = zfs[0] / (1024 ** 3)
                    disk_total = zfs[1] / (1024 ** 3)
                    disk_pct = (zfs[0] / zfs[1] * 100) if zfs[1] > 0 else 0
                else:
                    disk = psutil.disk_usage(DISK_MOUNT)
                    disk_pct, disk_used, disk_total = disk.percent, disk.used / (1024 ** 3), disk.total / (1024 ** 3)
            else:
                disk = psutil.disk_usage(DISK_MOUNT)
                disk_pct, disk_used, disk_total = disk.percent, disk.used / (1024 ** 3), disk.total / (1024 ** 3)

            # Format sizes appropriately
            if disk_total >= 1024:
                size_text = f'{disk_used / 1024:.1f}/{disk_total / 1024:.1f} TB'
            else:
                size_text = f'{disk_used:.0f}/{disk_total:.0f} GB'

            draw_bar(draw, L, y + 2, 200, 12, disk_pct)
            draw.text((215, y + 2), f'{disk_pct:.0f}%', fill=usage_color(disk_pct), font=fonts['small'], anchor='lt')
            draw.text((R, y + 2), size_text, fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')

            y += 18

            # IO speeds
            draw.text((L, y), f'R: {format_speed(metrics.disk_read_speed)}', fill=GREEN, font=fonts['tiny'], anchor='lt')
            draw.text((R, y), f'W: {format_speed(metrics.disk_write_speed)}', fill=YELLOW, font=fonts['tiny'], anchor='rt')
            y += 12
        except OSError:
            draw.text((L, y + 2), f'Mount {DISK_MOUNT} unavailable', fill=RED, font=fonts['tiny'], anchor='lt')
            y += 14

    # === NETWORK SECTION ===
    if SHOW_NETWORK:
        y = draw_section_header(draw, y, 'NETWORK', fonts)

        iface, ip_addr = get_active_interface()

        draw.text((L, y), iface, fill=LABEL_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((R, y), ip_addr, fill=MUTED_COLOR, font=fonts['tiny'], anchor='rt')
        y += 15

        # Upload / Download speeds
        draw.text((L, y), f'\u25bc {format_speed(metrics.net_down_speed)}', fill=GREEN, font=fonts['small'], anchor='lt')
        draw.text((R, y), f'\u25b2 {format_speed(metrics.net_up_speed)}', fill=YELLOW, font=fonts['small'], anchor='rt')
        y += 19

        # Network speed graph
        draw_net_graph(draw, L, y, R - L, 36, metrics.net_down_history, metrics.net_up_history)
        y += 40

        # Total transferred since boot
        net_io = psutil.net_io_counters()
        draw.text((L, y), f'Rx: {format_bytes(net_io.bytes_recv)}', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
        draw.text((R, y), f'Tx: {format_bytes(net_io.bytes_sent)}', fill=MUTED_COLOR, font=fonts['tiny'], anchor='rt')
        y += 12

    # === GPU SECTION ===
    if SHOW_GPU and metrics.gpu_available:
        gpu = metrics.gpu_info
        if gpu:
            y = draw_section_header(draw, y, 'GPU', fonts)

            gpu_pct = gpu['usage']
            draw_bar(draw, L, y + 2, 140, 12, gpu_pct)
            draw.text((155, y + 2), f'{gpu_pct}%', fill=usage_color(gpu_pct), font=fonts['small'], anchor='lt')
            gpu_temp = gpu['temp']
            draw.text((R, y + 2), f'{gpu_temp}\u00b0C', fill=temp_color(gpu_temp), font=fonts['small'], anchor='rt')
            y += 18

            # VRAM
            vram_pct = (gpu['vram_used'] / gpu['vram_total'] * 100) if gpu['vram_total'] > 0 else 0
            draw.text((L, y), 'VRAM', fill=MUTED_COLOR, font=fonts['tiny'], anchor='lt')
            draw_bar(draw, 45, y + 1, 120, 10, vram_pct)
            draw.text((R, y), f'{gpu["vram_used"]}/{gpu["vram_total"]} MB', fill=LABEL_COLOR, font=fonts['tiny'], anchor='rt')
            y += 12

    # === TOP PROCESSES SECTION ===
    if SHOW_PROCESSES:
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

            # How many processes can we fit?
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


def find_changed_rows(old_img, new_img):
    """Find rows that differ between two images."""
    old_arr = np.array(old_img)
    new_arr = np.array(new_img)

    # Compare each row
    diff = np.any(old_arr != new_arr, axis=(1, 2))
    changed_rows = np.where(diff)[0]

    if len(changed_rows) == 0:
        return []

    # Group consecutive rows into regions
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
    print(f'  Refresh rate: {REFRESH_RATE}s')

    print('Connecting to display...')
    lcd = LcdCommRevA(com_port=COM_PORT, display_width=320, display_height=480)
    lcd.SetBrightness(level=BRIGHTNESS)
    lcd.SetOrientation(Orientation.PORTRAIT)
    lcd.DisplayPILImage(Image.new('RGB', (320, 480), (0, 0, 0)))

    fonts = {
        'bold': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 20),
        'mono_med': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Bold.ttf'), 20),
        'big_mono': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Bold.ttf'), 24),
        'section': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Bold.ttf'), 12),
        'small': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 14),
        'tiny': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 11),
        'tiny_mono': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto-mono/RobotoMono-Regular.ttf'), 11),
        'event': ImageFont.truetype(os.path.join(FONT_DIR, 'roboto/Roboto-Regular.ttf'), 14),
    }

    # Initialize psutil cpu_percent (first call always returns 0)
    psutil.cpu_percent(interval=0)
    psutil.cpu_percent(interval=0, percpu=True)

    metrics = SystemMetrics()

    # Initial draw
    now = datetime.now()
    metrics.update()
    current_img = draw_screen(now, metrics, fonts)
    lcd.DisplayPILImage(current_img)
    prev_img = current_img.copy()

    print('Running... (Ctrl+C to stop)')
    try:
        while True:
            now = datetime.now()

            # Update speed metrics
            metrics.update()

            # Draw new frame
            current_img = draw_screen(now, metrics, fonts)

            # Find changed regions
            regions = find_changed_rows(prev_img, current_img)

            # Send only changed regions
            for y_start, y_end in regions:
                region = current_img.crop((0, y_start, WIDTH, y_end))
                lcd.DisplayPILImage(region, x=0, y=y_start)

            prev_img = current_img.copy()

            time_module.sleep(REFRESH_RATE)
    except KeyboardInterrupt:
        print('\nStopping...')


if __name__ == '__main__':
    main()
