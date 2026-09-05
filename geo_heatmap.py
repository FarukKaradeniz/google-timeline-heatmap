#!/usr/bin/env python3
"""
geo_heatmap.py
==============
Google Timeline / Konum Geçmişi verinizden interaktif bir ısı haritası (HTML)
üretir. Google'ın 2024 sonrası "cihaz üzerinde Timeline" JSON formatını
(semanticSegments) ve eski Google Takeout formatını destekler.

Desteklenen girdi dosyaları:
  1. Yeni format: telefonunuzdan "Export Timeline Data" ile aldığınız
     Timeline.json (üst seviyede bir liste, her öğede "visit", "activity"
     veya "timelinePath" alanı bulunur).
  2. Eski format: Google Takeout'tan gelen Records.json / Location History.json
     (üst seviyede {"locations": [...]}, her öğede "latitudeE7"/"longitudeE7"
     veya "timestamp"/"latE7" gibi alanlar bulunur).

Kurulum:
    pip install -r requirements.txt

Kullanım:
    python geo_heatmap.py Timeline.json
    python geo_heatmap.py Timeline.json -o harita.html
    python geo_heatmap.py Timeline.json --min-date 2023-01-01 --max-date 2023-12-31
    python geo_heatmap.py Records.json Timeline.json   (birden fazla dosya birleştirilir)

Çıktı:
    Varsayılan olarak "heatmap.html" adında, tarayıcıda açılabilen tek bir
    HTML dosyası üretir ve otomatik olarak açar.
"""

import argparse
import json
import re
import sys
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path

try:
    import folium
    from folium.plugins import HeatMap
except ImportError:
    sys.exit(
        "Hata: 'folium' paketi bulunamadı.\n"
        "Kurmak için: pip install -r requirements.txt"
    )


# --------------------------------------------------------------------------- #
# Tarih ayrıştırma yardımcıları
# --------------------------------------------------------------------------- #

def parse_iso_datetime(value):
    """ISO 8601 tarih metnini (Z veya +HH:MM ile) datetime nesnesine çevirir."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_geo_string(value):
    """'geo:41.0082,28.9784' formatındaki metni (lat, lon) tuple'ına çevirir."""
    if not isinstance(value, str):
        return None
    match = re.match(r"geo:(-?[\d.]+),\s*(-?[\d.]+)", value)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


# --------------------------------------------------------------------------- #
# Format 1: Yeni Google Timeline formatı (semanticSegments / cihaz üzerinde)
# --------------------------------------------------------------------------- #

def extract_points_new_format(data):
    """
    Üst seviyesi bir liste olan ve 'visit' / 'activity' / 'timelinePath'
    anahtarları içeren yeni Google Timeline JSON'unu ayrıştırır.
    Her nokta (lat, lon, datetime) olarak döner.
    """
    points = []
    for segment in data:
        if not isinstance(segment, dict):
            continue

        start = parse_iso_datetime(segment.get("startTime"))

        if "visit" in segment:
            loc = segment["visit"].get("topCandidate", {}).get("placeLocation")
            geo = parse_geo_string(loc)
            if geo:
                points.append((geo[0], geo[1], start))

        if "activity" in segment:
            activity = segment["activity"]
            for key in ("start", "end"):
                geo = parse_geo_string(activity.get(key))
                if geo:
                    points.append((geo[0], geo[1], start))

        if "timelinePath" in segment:
            for step in segment["timelinePath"]:
                geo = parse_geo_string(step.get("point"))
                if geo:
                    points.append((geo[0], geo[1], start))

    return points


# --------------------------------------------------------------------------- #
# Format 2: Eski Google Takeout formatı ({"locations": [...]})
# --------------------------------------------------------------------------- #

def extract_points_legacy_format(data):
    """
    Eski Google Takeout Location History formatını ayrıştırır.
    Örnek öğe: {"timestampMs": "...", "latitudeE7": ..., "longitudeE7": ...}
    veya daha yeni: {"timestamp": "...", "latE7": ..., "lngE7": ...}
    """
    points = []
    for loc in data.get("locations", []):
        try:
            lat = loc.get("latitudeE7", loc.get("latE7"))
            lon = loc.get("longitudeE7", loc.get("lngE7"))
            if lat is None or lon is None:
                continue
            lat, lon = lat / 1e7, lon / 1e7

            ts = loc.get("timestamp")
            if ts:
                dt = parse_iso_datetime(ts)
            else:
                ts_ms = loc.get("timestampMs")
                dt = datetime.fromtimestamp(int(ts_ms) / 1000) if ts_ms else None

            points.append((lat, lon, dt))
        except (TypeError, ValueError):
            continue

    return points


# --------------------------------------------------------------------------- #
# Dosya yükleme (JSON veya Takeout .zip)
# --------------------------------------------------------------------------- #

def load_points_from_file(path):
    """Bir dosyadan (JSON veya .zip içindeki JSON'lardan) noktaları çıkarır."""
    path = Path(path)

    if path.suffix.lower() == ".zip":
        points = []
        with zipfile.ZipFile(path) as zf:
            json_names = [n for n in zf.namelist() if n.lower().endswith(".json")]
            for name in json_names:
                with zf.open(name) as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        continue
                    points.extend(extract_points_from_data(data))
        return points

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return extract_points_from_data(data)


def extract_points_from_data(data):
    if isinstance(data, list):
        return extract_points_new_format(data)
    if isinstance(data, dict) and "locations" in data:
        return extract_points_legacy_format(data)
    return []


# --------------------------------------------------------------------------- #
# Ana akış
# --------------------------------------------------------------------------- #

def filter_by_date(points, min_date, max_date):
    if not min_date and not max_date:
        return points

    filtered = []
    for lat, lon, dt in points:
        if dt is None:
            continue
        day = dt.date()
        if min_date and day < min_date:
            continue
        if max_date and day > max_date:
            continue
        filtered.append((lat, lon, dt))
    return filtered


def build_map(points, output, zoom_start, radius, blur, min_opacity, max_zoom, tiles):
    if not points:
        sys.exit("Hata: Seçilen dosyalarda / tarih aralığında hiç konum bulunamadı.")

    avg_lat = sum(p[0] for p in points) / len(points)
    avg_lon = sum(p[1] for p in points) / len(points)

    fmap = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=zoom_start,
        tiles=tiles,
    )

    heat_data = [[lat, lon] for lat, lon, _ in points]
    HeatMap(
        heat_data,
        radius=radius,
        blur=blur,
        min_opacity=min_opacity,
        max_zoom=max_zoom,
    ).add_to(fmap)
    fmap.save(output)
    return output


def parse_date_arg(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Geçersiz tarih formatı: {value} (YYYY-MM-DD olmalı)")


def main():
    parser = argparse.ArgumentParser(
        description="Google Timeline / Konum Geçmişi verinizden ısı haritası üretir."
    )
    parser.add_argument(
        "file", nargs="+",
        help="Timeline.json, Records.json veya Takeout .zip dosyası (birden fazla olabilir)"
    )
    parser.add_argument("-o", "--output", default="heatmap.html", help="Çıktı HTML dosyasının yolu (varsayılan: heatmap.html)")
    parser.add_argument("--min-date", type=parse_date_arg, default=None, help="En eski tarih (YYYY-MM-DD)")
    parser.add_argument("--max-date", type=parse_date_arg, default=None, help="En yeni tarih (YYYY-MM-DD)")
    parser.add_argument("--map", "-m", dest="tiles", default="OpenStreetMap", help="Harita katmanı (örn. 'OpenStreetMap', 'CartoDB dark_matter')")
    parser.add_argument("-z", "--zoom-start", type=int, default=6, help="Başlangıç zoom seviyesi (varsayılan: 6)")
    parser.add_argument("-r", "--radius", type=int, default=7, help="Her noktanın yarıçapı (varsayılan: 7)")
    parser.add_argument("-b", "--blur", type=int, default=4, help="Bulanıklık miktarı (varsayılan: 4)")
    parser.add_argument("-mo", "--min-opacity", type=float, default=0.2, help="Minimum opaklık (varsayılan: 0.2)")
    parser.add_argument("-mz", "--max-zoom", type=int, default=4, help="Isı haritasının maksimum zoom'u (varsayılan: 4)")
    parser.add_argument("--no-open", action="store_true", help="Oluşturduktan sonra tarayıcıda otomatik açma")

    args = parser.parse_args()

    all_points = []
    for file_path in args.file:
        print(f"Okunuyor: {file_path}")
        pts = load_points_from_file(file_path)
        print(f"  -> {len(pts)} nokta bulundu")
        all_points.extend(pts)

    if args.min_date or args.max_date:
        before = len(all_points)
        all_points = filter_by_date(all_points, args.min_date, args.max_date)
        print(f"Tarih filtresi uygulandı: {before} -> {len(all_points)} nokta")

    print(f"Toplam {len(all_points)} nokta ile harita oluşturuluyor...")
    output_path = build_map(
        all_points,
        args.output,
        args.zoom_start,
        args.radius,
        args.blur,
        args.min_opacity,
        args.max_zoom,
        args.tiles,
    )
    print(f"Harita kaydedildi: {output_path}")

    if not args.no_open:
        webbrowser.open("file://" + str(Path(output_path).resolve()))


if __name__ == "__main__":
    main()
