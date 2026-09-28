# 🛰️ Satellite GeoTIFF Capture — Streamlit App

**Author:** Zia U. Ahmed, Ph.D. | Uppata Analytics LLC  
**GitHub:** [zia207](https://github.com/zia207)

---

## What it does

Captures satellite imagery tiles for any user-defined AOI (Area of Interest)  
and saves them as georeferenced **GeoTIFF** files ready for QGIS, ArcGIS, or rasterio.

## Tile Sources

| Source | Max Zoom | Notes |
|--------|----------|-------|
| Google Satellite | 20 | High-res globally |
| Google Hybrid | 20 | Satellite + labels |
| Google Terrain | 18 | Topographic |
| ESRI World Imagery | 19 | Good rural coverage |
| OpenStreetMap | 19 | Open license |
| Stamen Terrain | 18 | Stylised terrain |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

## Usage

1. **Select tile source** and **zoom level** in the sidebar
2. **Pan/zoom the map** to your AOI — the yellow rectangle auto-fits the visible area
   — OR — switch to **Enter coordinates** mode and type bbox manually
3. Set **output directory** and **filename prefix**
4. Click **📥 Capture GeoTIFF**
5. Download PNG / GeoTIFF / Metadata JSON from the **Preview & Export** tab

## Output Files

| File | Description |
|------|-------------|
| `capture_YYYYMMDD_HHMMSS.tif` | Georeferenced GeoTIFF (EPSG:4326, LZW) |
| `capture_YYYYMMDD_HHMMSS.png` | Plain PNG preview |
| `capture_YYYYMMDD_HHMMSS_meta.json` | Metadata: bounds, zoom, source, resolution |

## Open in QGIS

`Layer` → `Add Raster Layer` → select `.tif` — CRS is embedded automatically.

## Open in Python

```python
import rasterio
with rasterio.open("capture.tif") as src:
    print(src.crs)        # EPSG:4326
    print(src.bounds)     # BoundingBox(left, bottom, right, top)
    img = src.read()      # numpy array (3, H, W)
```

## Tile Count Guidelines

| AOI size | Zoom | ~Tiles | ~Time |
|----------|------|--------|-------|
| Small field (~1 km²) | 18 | 10–30 | 5 s |
| Village (~5 km²) | 17 | 20–60 | 15 s |
| District (~100 km²) | 15 | 50–150 | 30 s |
| Province (~1000 km²) | 13 | 30–80 | 20 s |

## Legal Note

Tile usage is subject to the terms of service of each provider.  
Use responsibly and for research/educational purposes.
