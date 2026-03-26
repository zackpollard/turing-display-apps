# Weather Display

A weather display app for the Turing 3.5" USB-C smart screen (320x480, portrait).

Uses the OpenWeatherMap free tier API to show current conditions, hourly forecast, and multi-day forecast.

## Setup

1. Get a free API key from [OpenWeatherMap](https://openweathermap.org/api)
2. Copy the example config and fill in your details:
   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml with your API key and coordinates
   ```
3. Install dependencies (from repo root):
   ```bash
   pip install -r requirements.txt
   # Also needs: pip install requests
   ```

## Running

```bash
cd /home/zack/Source/turing-display-apps
source venv/bin/activate
python apps/weather/weather_display.py
```

## Display Layout

- **Header**: City name, current temperature (large), conditions text, feels-like temperature, clock
- **Conditions**: Humidity with bar, wind speed/direction/gusts, pressure, visibility, cloud cover, sunrise/sunset
- **Hourly**: Next 8 forecast periods showing time, temperature, and rain probability
- **Daily**: Next 4 days with day name, high/low temps, condition, and rain probability

## API Usage

The app makes 2 API calls per refresh (current + forecast). With the default 10-minute interval, that's approximately 288 calls per day, well within the free tier limit of 1,000 calls/day.

## Color Scheme

Temperature is color-coded: blue (cold) through cyan (cool), white (mild), orange (warm), to red (hot). Rain probability uses blue shades. The dark background matches the calendar app style.
