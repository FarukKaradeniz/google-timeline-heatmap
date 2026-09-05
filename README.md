# Google Timeline Heatmap

A simple Python script that turns your Google Timeline (Location History) data into an interactive heatmap. It builds a single, self-contained HTML file using [Folium](https://python-visualization.github.io/folium/) and [Leaflet.js](https://leafletjs.com/) — no server, API key, or internet connection required (other than to load the map tiles).

Supports both the new **on-device Timeline** JSON format that Google switched to at the end of 2024 (`semanticSegments`), and the older Google Takeout export format (`locations` array).

## Features

- Supports both the new on-device format (`visit` / `activity` / `timelinePath`) and the legacy Takeout format (`locations` array)
- Accepts a raw Takeout `.zip` file directly and automatically finds the JSON inside it
- Can merge multiple files into a single map
- Date-range filtering (`--min-date` / `--max-date`)
- Customizable heatmap appearance (radius, blur, zoom, opacity, map tile layer)

## Getting your data

Since December 2024, Google stores Timeline data on your device rather than in the cloud. To export it:

**Android:** Settings → Location → Location Services → Timeline → **Export Timeline Data**
**iOS:** Google Maps app → Settings → Personal Content / Timeline

This downloads a file named `Timeline.json`.

If you have an older (pre-2024) Takeout archive, a `Records.json` or `.zip` file exported from [Google Takeout](https://takeout.google.com/) (selecting "Location History (Timeline)") also works.

## Installation

```bash
git clone https://github.com/FarukKaradeniz/google-timeline-heatmap.git
cd google-timeline-heatmap

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

> **Note (macOS/Homebrew):** If you get an `externally-managed-environment` error, make sure you followed the venv steps above — installing directly into the system Python is no longer recommended.

## Usage

```bash
python geo_heatmap.py Timeline.json
```

This generates `heatmap.html` and opens it automatically in your browser.

### More examples

```bash
# Custom output filename
python geo_heatmap.py Timeline.json -o map.html

# Filter by date range
python geo_heatmap.py Timeline.json --min-date 2023-01-01 --max-date 2023-12-31

# Merge multiple files
python geo_heatmap.py Records.json Timeline.json

# Dark map tiles and a larger radius
python geo_heatmap.py Timeline.json -m "CartoDB dark_matter" -r 12 -b 8

# Generate the file without opening it in a browser
python geo_heatmap.py Timeline.json --no-open
```

### All options

```
usage: geo_heatmap.py [-h] [-o OUTPUT] [--min-date YYYY-MM-DD]
                       [--max-date YYYY-MM-DD] [--map MAP] [-z ZOOM_START]
                       [-r RADIUS] [-b BLUR] [-mo MIN_OPACITY] [-mz MAX_ZOOM]
                       [--no-open]
                       file [file ...]

positional arguments:
  file                  Timeline.json, Records.json, or a Takeout .zip file
                        (multiple files can be passed)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Path to the output HTML file (default: heatmap.html)
  --min-date YYYY-MM-DD
                        Earliest date to include
  --max-date YYYY-MM-DD
                        Latest date to include
  --map MAP, -m MAP     Map tile layer (e.g. 'OpenStreetMap',
                        'CartoDB dark_matter')
  -z ZOOM_START, --zoom-start ZOOM_START
                        Initial zoom level (default: 6)
  -r RADIUS, --radius RADIUS
                        Radius of each point (default: 7)
  -b BLUR, --blur BLUR  Amount of blur (default: 4)
  -mo MIN_OPACITY, --min-opacity MIN_OPACITY
                        Minimum opacity (default: 0.2)
  -mz MAX_ZOOM, --max-zoom MAX_ZOOM
                        Maximum zoom of the heatmap (default: 4)
  --no-open             Don't automatically open the result in a browser
```

## Supported file formats

| Format | Description |
|---|---|
| `Timeline.json` | New on-device format, exported from your phone via "Export Timeline Data" (`semanticSegments`) |
| `Records.json` / `Location History.json` | Legacy Google Takeout format (`{"locations": [...]}`) |
| `takeout-*.zip` | Raw Takeout `.zip` output — the JSON inside is found automatically |

## Privacy

This script runs entirely locally. Your location data is never sent anywhere; it's only converted into an HTML file on the same machine. Keep in mind that the generated `heatmap.html` (and your input JSON files) can contain sensitive location information — avoid uploading them to a public location.

## License

[MIT](LICENSE)
