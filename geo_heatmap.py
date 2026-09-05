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


def build_map(points, output, zoom_start, radius, blur, min_opacity, max_zoom, tiles,
              interactive_filter=True):
    if not points:
        sys.exit("Hata: Seçilen dosyalarda / tarih aralığında hiç konum bulunamadı.")

    avg_lat = sum(p[0] for p in points) / len(points)
    avg_lon = sum(p[1] for p in points) / len(points)

    fmap = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=zoom_start,
        tiles=tiles,
    )

    if not interactive_filter:
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

    add_interactive_heatmap(fmap, points, radius, blur, min_opacity, max_zoom)
    fmap.save(output)
    return output


def add_interactive_heatmap(fmap, points, radius, blur, min_opacity, max_zoom):
    """
    Haritaya, yıl aralığına göre filtrelenebilen interaktif bir ısı haritası
    katmanı ve bunu kontrol eden bir kaydırıcı paneli ekler. Leaflet.heat
    doğrudan gömülü olarak eklenir; harici bir CDN isteğine ihtiyaç duymaz.
    """
    map_name = fmap.get_name()

    heat_points = []
    for lat, lon, dt in points:
        year = dt.year if dt is not None else None
        heat_points.append([round(lat, 5), round(lon, 5), year])

    years = [p[2] for p in heat_points if p[2] is not None]
    year_min = min(years) if years else datetime.now().year
    year_max = max(years) if years else datetime.now().year

    data_json = json.dumps(heat_points, separators=(",", ":"))

    css = """
    <style>
    #heatmap-panel {
      position: absolute; left: 18px; bottom: 22px; z-index: 1000;
      background: #12161bdd; border: 1px solid #232a32; border-radius: 10px;
      padding: 14px 16px 16px 16px; width: 320px; max-width: calc(100vw - 36px);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; color: #e7ebef;
      box-shadow: 0 8px 28px rgba(0,0,0,0.45);
    }
    #heatmap-panel .row-label {
      display:flex; justify-content:space-between; align-items:baseline;
      font-size:11.5px; color:#8b96a3; text-transform:uppercase;
      letter-spacing:0.6px; margin-bottom:8px;
    }
    #heatmap-year-range-label { color:#e7ebef; font-weight:600; text-transform:none; font-size:13px; }
    #heatmap-panel .slider-wrap { position:relative; height:30px; margin-bottom:4px; }
    #heatmap-panel input[type=range] {
      -webkit-appearance:none; appearance:none; position:absolute;
      left:0; right:0; top:8px; width:100%; height:4px; background:transparent;
      pointer-events:none; margin:0;
    }
    #heatmap-panel input[type=range]::-webkit-slider-thumb {
      -webkit-appearance:none; pointer-events:all; width:16px; height:16px;
      border-radius:50%; background:#ff6a3d; border:2px solid #0b0e11; cursor:pointer; margin-top:-6px;
    }
    #heatmap-panel input[type=range]::-moz-range-thumb {
      pointer-events:all; width:14px; height:14px; border-radius:50%;
      background:#ff6a3d; border:2px solid #0b0e11; cursor:pointer;
    }
    #heatmap-track-bg { position:absolute; left:0; right:0; top:13px; height:4px; border-radius:2px; background:#262d35; }
    #heatmap-track-fill { position:absolute; top:13px; height:4px; border-radius:2px; background:#ff6a3d; }
    #heatmap-year-ticks { display:flex; justify-content:space-between; font-size:10px; color:#5b6570; margin-bottom:14px; padding:0 1px; }
    #heatmap-panel .btn-row { display:flex; gap:8px; }
    #heatmap-panel .btn {
      flex:1; background:#1a2027; border:1px solid #232a32; color:#8b96a3;
      font-size:12px; padding:7px 8px; border-radius:6px; cursor:pointer;
      transition: background 0.15s, color 0.15s; text-align:center; user-select:none;
    }
    #heatmap-panel .btn:hover { background:#232b34; color:#e7ebef; }
    #heatmap-panel .btn.active { background:#7a3222; color:#ffd7c9; border-color:#a8462a; }
    </style>
    """

    html_ui = f"""
    <div id="heatmap-panel">
      <div class="row-label">
        <span>Y\u0131l aral\u0131\u011f\u0131</span>
        <span id="heatmap-year-range-label"></span>
      </div>
      <div class="slider-wrap">
        <div id="heatmap-track-bg"></div>
        <div id="heatmap-track-fill"></div>
        <input type="range" id="heatmap-year-min" />
        <input type="range" id="heatmap-year-max" />
      </div>
      <div id="heatmap-year-ticks"></div>
      <div class="btn-row">
        <div class="btn active" id="heatmap-btn-all">T\u00fcm zamanlar</div>
        <div class="btn" id="heatmap-btn-last-year">Son 12 ay</div>
        <div class="btn" id="heatmap-btn-reset-view">Harita\u0131 ortala</div>
      </div>
    </div>
    """

    # NOTE: {map_name} is the folium-generated JS variable holding the Leaflet map.
    js = f"""
    <script>
    /*!
     (c) 2014, Vladimir Agafonkin
     simpleheat, a tiny JavaScript library for drawing heatmaps with Canvas
     https://github.com/mourner/simpleheat
    */
    !function(){{"use strict";function t(i){{return this instanceof t?(this._canvas=i="string"==typeof i?document.getElementById(i):i,this._ctx=i.getContext("2d"),this._width=i.width,this._height=i.height,this._max=1,void this.clear()):new t(i)}}t.prototype={{defaultRadius:25,defaultGradient:{{.4:"blue",.6:"cyan",.7:"lime",.8:"yellow",1:"red"}},data:function(t,i){{return this._data=t,this}},max:function(t){{return this._max=t,this}},add:function(t){{return this._data.push(t),this}},clear:function(){{return this._data=[],this}},radius:function(t,i){{i=i||15;var a=this._circle=document.createElement("canvas"),s=a.getContext("2d"),e=this._r=t+i;return a.width=a.height=2*e,s.shadowOffsetX=s.shadowOffsetY=200,s.shadowBlur=i,s.shadowColor="black",s.beginPath(),s.arc(e-200,e-200,t,0,2*Math.PI,!0),s.closePath(),s.fill(),this}},gradient:function(t){{var i=document.createElement("canvas"),a=i.getContext("2d"),s=a.createLinearGradient(0,0,0,256);i.width=1,i.height=256;for(var e in t)s.addColorStop(e,t[e]);return a.fillStyle=s,a.fillRect(0,0,1,256),this._grad=a.getImageData(0,0,1,256).data,this}},draw:function(t){{this._circle||this.radius(this.defaultRadius),this._grad||this.gradient(this.defaultGradient);var i=this._ctx;i.clearRect(0,0,this._width,this._height);for(var a,s=0,e=this._data.length;e>s;s++)a=this._data[s],i.globalAlpha=Math.max(a[2]/this._max,t||.05),i.drawImage(this._circle,a[0]-this._r,a[1]-this._r);var n=i.getImageData(0,0,this._width,this._height);return this._colorize(n.data,this._grad),i.putImageData(n,0,0),this}},_colorize:function(t,i){{for(var a,s=3,e=t.length;e>s;s+=4)a=4*t[s],a&&(t[s-3]=i[a],t[s-2]=i[a+1],t[s-1]=i[a+2])}}}},window.simpleheat=t}}(),
    L.HeatLayer=(L.Layer?L.Layer:L.Class).extend({{initialize:function(t,i){{this._latlngs=t,L.setOptions(this,i)}},setLatLngs:function(t){{return this._latlngs=t,this.redraw()}},addLatLng:function(t){{return this._latlngs.push(t),this.redraw()}},setOptions:function(t){{return L.setOptions(this,t),this._heat&&this._updateOptions(),this.redraw()}},redraw:function(){{return!this._heat||this._frame||this._map._animating||(this._frame=L.Util.requestAnimFrame(this._redraw,this)),this}},onAdd:function(t){{this._map=t,this._canvas||this._initCanvas(),t._panes.overlayPane.appendChild(this._canvas),t.on("moveend",this._reset,this),t.options.zoomAnimation&&L.Browser.any3d&&t.on("zoomanim",this._animateZoom,this),this._reset()}},onRemove:function(t){{t.getPanes().overlayPane.removeChild(this._canvas),t.off("moveend",this._reset,this),t.options.zoomAnimation&&t.off("zoomanim",this._animateZoom,this)}},addTo:function(t){{return t.addLayer(this),this}},_initCanvas:function(){{var t=this._canvas=L.DomUtil.create("canvas","leaflet-heatmap-layer leaflet-layer"),i=L.DomUtil.testProp(["transformOrigin","WebkitTransformOrigin","msTransformOrigin"]);t.style[i]="50% 50%";var a=this._map.getSize();t.width=a.x,t.height=a.y;var s=this._map.options.zoomAnimation&&L.Browser.any3d;L.DomUtil.addClass(t,"leaflet-zoom-"+(s?"animated":"hide")),this._heat=simpleheat(t),this._updateOptions()}},_updateOptions:function(){{this._heat.radius(this.options.radius||this._heat.defaultRadius,this.options.blur),this.options.gradient&&this._heat.gradient(this.options.gradient),this.options.max&&this._heat.max(this.options.max)}},_reset:function(){{var t=this._map.containerPointToLayerPoint([0,0]);L.DomUtil.setPosition(this._canvas,t);var i=this._map.getSize();this._heat._width!==i.x&&(this._canvas.width=this._heat._width=i.x),this._heat._height!==i.y&&(this._canvas.height=this._heat._height=i.y),this._redraw()}},_redraw:function(){{var t,i,a,s,e,n,h,o,r,d=[],_=this._heat._r,l=this._map.getSize(),m=new L.Bounds(L.point([-_,-_]),l.add([_,_])),c=void 0===this.options.max?1:this.options.max,u=void 0===this.options.maxZoom?this._map.getMaxZoom():this.options.maxZoom,f=1/Math.pow(2,Math.max(0,Math.min(u-this._map.getZoom(),12))),g=_/2,p=[],v=this._map._getMapPanePos(),w=v.x%g,y=v.y%g;for(t=0,i=this._latlngs.length;i>t;t++)if(a=this._map.latLngToContainerPoint(this._latlngs[t]),m.contains(a)){{e=Math.floor((a.x-w)/g)+2,n=Math.floor((a.y-y)/g)+2;var x=void 0!==this._latlngs[t].alt?this._latlngs[t].alt:void 0!==this._latlngs[t][2]?+this._latlngs[t][2]:1;r=x*f,p[n]=p[n]||[],s=p[n][e],s?(s[0]=(s[0]*s[2]+a.x*r)/(s[2]+r),s[1]=(s[1]*s[2]+a.y*r)/(s[2]+r),s[2]+=r):p[n][e]=[a.x,a.y,r]}}for(t=0,i=p.length;i>t;t++)if(p[t])for(h=0,o=p[t].length;o>h;h++)s=p[t][h],s&&d.push([Math.round(s[0]),Math.round(s[1]),Math.min(s[2],c)]);this._heat.data(d).draw(this.options.minOpacity),this._frame=null}},_animateZoom:function(t){{var i=this._map.getZoomScale(t.zoom),a=this._map._getCenterOffset(t.center)._multiplyBy(-i).subtract(this._map._getMapPanePos());L.DomUtil.setTransform?L.DomUtil.setTransform(this._canvas,a,i):this._canvas.style[L.DomUtil.TRANSFORM]=L.DomUtil.getTranslateString(a)+" scale("+i+")"}}}}),L.heatLayer=function(t,i){{return new L.HeatLayer(t,i)}};

    (function() {{
      var RAW_POINTS = {data_json};
      var YEAR_MIN = {year_min};
      var YEAR_MAX = {year_max};
      var mapObj = {map_name};
      var dataBounds = L.latLngBounds(RAW_POINTS.map(function(p) {{ return [p[0], p[1]]; }}));
      var heatLayer = null;

      function buildHeatPoints(yMin, yMax) {{
        var out = [];
        for (var i = 0; i < RAW_POINTS.length; i++) {{
          var p = RAW_POINTS[i];
          if (p[2] === null || (p[2] >= yMin && p[2] <= yMax)) out.push([p[0], p[1], 0.55]);
        }}
        return out;
      }}

      function render(yMin, yMax) {{
        var pts = buildHeatPoints(yMin, yMax);
        if (heatLayer) mapObj.removeLayer(heatLayer);
        heatLayer = L.heatLayer(pts, {{
          radius: {radius},
          blur: {blur},
          maxZoom: {max_zoom},
          minOpacity: {min_opacity},
          gradient: {{0.2: '#1a3a6e', 0.4: '#1f7a5c', 0.6: '#d9c33a', 0.8: '#e8752f', 1.0: '#e0332e'}}
        }}).addTo(mapObj);
      }}

      function ready(fn) {{
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
      }}

      ready(function() {{
        var sliderMin = document.getElementById('heatmap-year-min');
        var sliderMax = document.getElementById('heatmap-year-max');
        sliderMin.min = YEAR_MIN; sliderMin.max = YEAR_MAX; sliderMin.value = YEAR_MIN;
        sliderMax.min = YEAR_MIN; sliderMax.max = YEAR_MAX; sliderMax.value = YEAR_MAX;

        var trackFill = document.getElementById('heatmap-track-fill');
        var rangeLabel = document.getElementById('heatmap-year-range-label');
        var ticksEl = document.getElementById('heatmap-year-ticks');
        var btnAll = document.getElementById('heatmap-btn-all');
        var btnLastYear = document.getElementById('heatmap-btn-last-year');
        var btnReset = document.getElementById('heatmap-btn-reset-view');

        for (var y = YEAR_MIN; y <= YEAR_MAX; y++) {{
          var span = document.createElement('span');
          span.textContent = y;
          ticksEl.appendChild(span);
        }}

        function updateTrackVisual() {{
          var lo = parseInt(sliderMin.value), hi = parseInt(sliderMax.value);
          var spanLen = (YEAR_MAX - YEAR_MIN) || 1;
          var leftPct = ((lo - YEAR_MIN) / spanLen) * 100;
          var rightPct = ((hi - YEAR_MIN) / spanLen) * 100;
          trackFill.style.left = leftPct + '%';
          trackFill.style.width = (rightPct - leftPct) + '%';
          rangeLabel.textContent = (lo === hi) ? lo : (lo + ' \\u2013 ' + hi);
        }}

        function onSliderChange() {{
          var lo = parseInt(sliderMin.value);
          var hi = parseInt(sliderMax.value);
          if (lo > hi) {{ var t = lo; lo = hi; hi = t; }}
          updateTrackVisual();
          render(lo, hi);
          btnAll.classList.toggle('active', lo === YEAR_MIN && hi === YEAR_MAX);
          btnLastYear.classList.remove('active');
        }}

        sliderMin.addEventListener('input', onSliderChange);
        sliderMax.addEventListener('input', onSliderChange);

        btnAll.addEventListener('click', function() {{
          sliderMin.value = YEAR_MIN; sliderMax.value = YEAR_MAX;
          updateTrackVisual(); render(YEAR_MIN, YEAR_MAX);
          btnAll.classList.add('active'); btnLastYear.classList.remove('active');
        }});

        btnLastYear.addEventListener('click', function() {{
          sliderMin.value = YEAR_MAX; sliderMax.value = YEAR_MAX;
          updateTrackVisual(); render(YEAR_MAX, YEAR_MAX);
          btnLastYear.classList.add('active'); btnAll.classList.remove('active');
        }});

        btnReset.addEventListener('click', function() {{
          mapObj.fitBounds(dataBounds, {{padding: [40, 40]}});
        }});

        mapObj.fitBounds(dataBounds, {{padding: [40, 40]}});
        updateTrackVisual();
        render(YEAR_MIN, YEAR_MAX);
      }});
    }})();
    </script>
    """

    fmap.get_root().header.add_child(folium.Element(css))
    fmap.get_root().html.add_child(folium.Element(html_ui))
    fmap.get_root().script.add_child(folium.Element(js))


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
    parser.add_argument(
        "--no-time-filter", action="store_true",
        help="Haritaya interaktif yıl aralığı kaydırıcısı ekleme (varsayılan: eklenir)"
    )

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
        interactive_filter=not args.no_time_filter,
    )
    print(f"Harita kaydedildi: {output_path}")

    if not args.no_open:
        webbrowser.open("file://" + str(Path(output_path).resolve()))


if __name__ == "__main__":
    main()
