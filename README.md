# Google Timeline Heatmap

Google Timeline (Konum Geçmişi) verinizden interaktif bir ısı haritası (heatmap) üreten basit bir Python scripti. [luka1199/geo-heatmap](https://github.com/luka1199/geo-heatmap) projesinden ilham alınmıştır; farkı, Google'ın 2024 sonrasında kullanıma aldığı **cihaz üzerinde saklanan Timeline** JSON formatını (`semanticSegments`) da desteklemesidir.

[Folium](https://python-visualization.github.io/folium/) ve [Leaflet.js](https://leafletjs.com/) kullanılarak, sonuç tek bir HTML dosyası olarak üretilir — sunucu, API anahtarı ya da internet bağlantısı gerektirmez (harita fayanslarını göstermek dışında).

## Özellikler

- Yeni format (**cihaz üzerinde Timeline** — `visit` / `activity` / `timelinePath`) ve eski Google Takeout formatının (`locations` dizisi) her ikisini de destekler
- Takeout'un ham `.zip` dosyasını doğrudan kabul eder, içindeki JSON'u otomatik bulur
- Birden fazla dosyayı tek haritada birleştirebilir
- Tarih aralığına göre filtreleme (`--min-date` / `--max-date`)
- Isı haritası görünümünü özelleştirme (yarıçap, bulanıklık, zoom, opaklık, harita katmanı)

## Verinizi indirme

Google, Aralık 2024'ten itibaren Timeline verisini bulutta değil cihazınızda saklıyor. Verinizi almak için:

**Android:** Ayarlar → Konum → Konum Hizmetleri → Timeline → **Export Timeline Data**
**iOS:** Google Maps uygulaması → Ayarlar → Kişisel İçerik / Timeline

Bu, `Timeline.json` adında bir dosya indirir.

Eski (2024 öncesi) bir Takeout arşiviniz varsa, [Google Takeout](https://takeout.google.com/)'tan "Location History (Timeline)" seçilerek alınan `Records.json` veya `.zip` dosyası da kullanılabilir.

## Kurulum

```bash
git clone https://github.com/<kullanici-adiniz>/google-timeline-heatmap.git
cd google-timeline-heatmap

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

> **Not (macOS/Homebrew):** `externally-managed-environment` hatası alırsanız, yukarıdaki venv adımlarını izlediğinizden emin olun — sistem Python'ına doğrudan kurulum artık önerilmiyor.

## Kullanım

```bash
python geo_heatmap.py Timeline.json
```

Bu, `heatmap.html` dosyasını oluşturur ve otomatik olarak tarayıcınızda açar.

### Diğer örnekler

```bash
# Çıktı dosyasının adını belirtme
python geo_heatmap.py Timeline.json -o harita.html

# Tarih aralığına göre filtreleme
python geo_heatmap.py Timeline.json --min-date 2023-01-01 --max-date 2023-12-31

# Birden fazla dosyayı birleştirme
python geo_heatmap.py Records.json Timeline.json

# Koyu tema harita katmanı ve daha büyük yarıçap
python geo_heatmap.py Timeline.json -m "CartoDB dark_matter" -r 12 -b 8

# Tarayıcıda otomatik açmadan sadece dosya üretme
python geo_heatmap.py Timeline.json --no-open
```

### Tüm seçenekler

```
usage: geo_heatmap.py [-h] [-o OUTPUT] [--min-date YYYY-MM-DD]
                       [--max-date YYYY-MM-DD] [--map MAP] [-z ZOOM_START]
                       [-r RADIUS] [-b BLUR] [-mo MIN_OPACITY] [-mz MAX_ZOOM]
                       [--no-open]
                       file [file ...]

positional arguments:
  file                  Timeline.json, Records.json veya Takeout .zip
                        dosyası (birden fazla olabilir)

options:
  -h, --help            yardımı gösterir ve çıkar
  -o OUTPUT, --output OUTPUT
                        Çıktı HTML dosyasının yolu (varsayılan: heatmap.html)
  --min-date YYYY-MM-DD
                        En eski tarih
  --max-date YYYY-MM-DD
                        En yeni tarih
  --map MAP, -m MAP     Harita katmanı (örn. 'OpenStreetMap',
                        'CartoDB dark_matter')
  -z ZOOM_START, --zoom-start ZOOM_START
                        Başlangıç zoom seviyesi (varsayılan: 6)
  -r RADIUS, --radius RADIUS
                        Her noktanın yarıçapı (varsayılan: 7)
  -b BLUR, --blur BLUR  Bulanıklık miktarı (varsayılan: 4)
  -mo MIN_OPACITY, --min-opacity MIN_OPACITY
                        Minimum opaklık (varsayılan: 0.2)
  -mz MAX_ZOOM, --max-zoom MAX_ZOOM
                        Isı haritasının maksimum zoom'u (varsayılan: 4)
  --no-open             Oluşturduktan sonra tarayıcıda otomatik açma
```

## Desteklenen dosya formatları

| Format | Açıklama |
|---|---|
| `Timeline.json` | Telefondan "Export Timeline Data" ile alınan yeni format (`semanticSegments`) |
| `Records.json` / `Location History.json` | Eski Google Takeout formatı (`{"locations": [...]}`) |
| `takeout-*.zip` | Takeout'un ham `.zip` çıktısı — içindeki JSON otomatik bulunur |

## Gizlilik

Bu script tamamen yerel çalışır. Konum verileriniz hiçbir yere gönderilmez; yalnızca aynı makinede bir HTML dosyasına dönüştürülür. Üretilen `heatmap.html` dosyasını (veya girdi JSON dosyalarınızı) herkese açık bir yere yüklemeden önce hassas konum bilgisi içerdiğini unutmayın.

## Lisans

[MIT](LICENSE)
