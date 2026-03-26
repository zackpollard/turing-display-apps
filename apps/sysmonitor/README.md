# System Monitor Display

A system monitor for the Turing 3.5" USB-C smart screen (320x480, portrait). Displays real-time CPU, memory, disk, network, GPU, and top process information.

## Setup

1. Copy the example config:
   ```bash
   cp config.example.yaml config.yaml
   ```

2. Install dependencies (in addition to the base `requirements.txt`):
   ```bash
   pip install psutil
   ```

3. Edit `config.yaml` to adjust settings (serial port, brightness, which sections to show, etc.)

4. Run:
   ```bash
   cd /home/zack/Source/turing-display-apps
   source venv/bin/activate
   python apps/sysmonitor/sysmonitor_display.py
   ```

## Display Sections

- **Header**: Hostname, uptime, current time
- **CPU**: Usage percentage with bar, per-core mini bars, temperature, frequency
- **Memory**: RAM usage bar with percentage, used/total, swap usage
- **Disk**: Root partition usage, read/write IO speeds
- **Network**: Active interface + IP, upload/download speeds, total transferred
- **GPU**: Usage, temperature, VRAM (NVIDIA only via `nvidia-smi`, auto-skipped if unavailable)
- **Top Processes**: Top processes by CPU usage showing PID, name, CPU%, MEM%

## Configuration

All sections can be toggled on/off in `config.yaml`. The network interface can be auto-detected or manually specified. See `config.example.yaml` for all options.

## Color Coding

- Usage bars: green (<60%), yellow (60-85%), red (>85%)
- Temperatures: green (<60C), yellow (60-80C), red (>80C)
