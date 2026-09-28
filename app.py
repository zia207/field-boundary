"""
╔══════════════════════════════════════════════════════════════════╗
║   Satellite GeoTIFF Capture — Streamlit App                     ║
║   Author : Zia U. Ahmed, Ph.D. | Uppata Analytics LLC           ║
║   Capture Google/OSM satellite tiles for any AOI as GeoTIFF     ║
╚══════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import numpy as np
import os
import math
import time
import io
from PIL import Image
from datetime import datetime
import json

# ── Optional GeoTIFF support (graceful fallback) ─────────────────────────────
try:
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS
    RASTERIO_OK = True
except ImportError:
    RASTERIO_OK = False

try:
    from pyproj import Transformer
    PYPROJ_OK = True
except ImportError:
    PYPROJ_OK = False

try:
    import mercantile
    MERCANTILE_OK = True
except ImportError:
    MERCANTILE_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Satellite GeoTIFF Capture",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# STYLES
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #0f1117; }
.block-container { padding-top: 1.2rem; }
.stButton > button {
    width: 100%; border-radius: 8px; font-weight: 600;
    background: linear-gradient(135deg,#1a6b3c,#0d4f2c);
    color: white; border: none; padding: 0.55rem 1rem;
    transition: opacity .2s;
}
.stButton > button:hover { opacity: 0.85; }
.metric-card {
    background: #1a1d2e; border: 1px solid #2a2d45;
    border-radius: 10px; padding: 14px 18px; margin: 4px 0;
}
.metric-card .label { font-size:11px; color:#8899bb; text-transform:uppercase; letter-spacing:.06em; }
.metric-card .value { font-size:18px; font-weight:700; color:#e0e4ff; margin-top:2px; }
.tile-badge {
    display:inline-block; background:#162; color:#6f6; border-radius:4px;
    padding:2px 8px; font-size:12px; font-family:monospace; margin:2px;
}
.info-box {
    background:#131625; border:1px solid #1f2845; border-radius:8px;
    padding:12px 16px; font-size:13px; color:#c0c8e8; line-height:1.7;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TILE SOURCES
# ─────────────────────────────────────────────────────────────────────────────
TILE_SOURCES = {
    "Google Satellite": {
        "url"      : "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "attr"     : "© Google",
        "max_zoom" : 20,
        "tile_size": 256,
    },
    "Google Hybrid (Satellite + Labels)": {
        "url"      : "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "attr"     : "© Google",
        "max_zoom" : 20,
        "tile_size": 256,
    },
    "Google Terrain": {
        "url"      : "https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        "attr"     : "© Google",
        "max_zoom" : 18,
        "tile_size": 256,
    },
    "ESRI World Imagery": {
        "url"      : "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr"     : "© Esri",
        "max_zoom" : 19,
        "tile_size": 256,
    },
    "OpenStreetMap": {
        "url"      : "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attr"     : "© OpenStreetMap contributors",
        "max_zoom" : 19,
        "tile_size": 256,
    },
    "Stamen Terrain": {
        "url"      : "https://stamen-tiles.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
        "attr"     : "© Stamen Design",
        "max_zoom" : 18,
        "tile_size": 256,
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept"         : "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer"        : "https://www.google.com/maps/",
}

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def deg2num(lat, lon, zoom):
    """Lat/lon → tile XY at given zoom."""
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return x, y


def num2deg(x, y, zoom):
    """Tile XY → top-left lat/lon of tile."""
    n = 2 ** zoom
    lon = x / n * 360 - 180
    lat_r = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_r)
    return lat, lon


def tile_bbox_wgs84(x, y, zoom):
    """Return (west, south, east, north) WGS84 for a tile."""
    north, west = num2deg(x,   y,   zoom)
    south, east = num2deg(x+1, y+1, zoom)
    return west, south, east, north


def estimate_tile_count(bbox, zoom):
    x_min, y_min = deg2num(bbox["max_lat"], bbox["min_lon"], zoom)
    x_max, y_max = deg2num(bbox["min_lat"], bbox["max_lon"], zoom)
    return (x_max - x_min + 1) * (y_max - y_min + 1)


def fetch_tile(url_template, x, y, z, retries=3):
    url = url_template.replace("{x}", str(x)).replace("{y}", str(y)).replace("{z}", str(z))
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            time.sleep(0.4 * (attempt + 1))
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    return None


def stitch_tiles(bbox, zoom, url_template, tile_size=256, progress_cb=None):
    """Download and stitch all tiles covering bbox into one PIL image."""
    x_min, y_min = deg2num(bbox["max_lat"], bbox["min_lon"], zoom)
    x_max, y_max = deg2num(bbox["min_lat"], bbox["max_lon"], zoom)

    nx = x_max - x_min + 1
    ny = y_max - y_min + 1
    total = nx * ny

    canvas = Image.new("RGB", (nx * tile_size, ny * tile_size), (30, 30, 40))

    fetched = 0
    for row, ty in enumerate(range(y_min, y_max + 1)):
        for col, tx in enumerate(range(x_min, x_max + 1)):
            tile = fetch_tile(url_template, tx, ty, zoom)
            if tile:
                canvas.paste(tile, (col * tile_size, row * tile_size))
            fetched += 1
            if progress_cb:
                progress_cb(fetched / total, f"Tile {fetched}/{total}  [{tx},{ty}]")
            time.sleep(0.05)   # polite rate limit

    # Crop to exact AOI bounds
    # Top-left corner of the tile grid
    tl_lat, tl_lon = num2deg(x_min, y_min, zoom)
    br_lat, br_lon = num2deg(x_max + 1, y_max + 1, zoom)

    lon_range = br_lon - tl_lon
    lat_range = tl_lat - br_lat   # positive (lat decreases downward)

    img_w, img_h = canvas.size
    # Crop pixel offsets
    left  = int((bbox["min_lon"] - tl_lon) / lon_range * img_w)
    right = int((bbox["max_lon"] - tl_lon) / lon_range * img_w)
    top   = int((tl_lat - bbox["max_lat"]) / lat_range * img_h)
    bot   = int((tl_lat - bbox["min_lat"]) / lat_range * img_h)

    left  = max(0, min(left,  img_w - 1))
    right = max(left + 1, min(right, img_w))
    top   = max(0, min(top,  img_h - 1))
    bot   = max(top + 1, min(bot,  img_h))

    cropped = canvas.crop((left, top, right, bot))
    geo_bounds = {
        "west" : bbox["min_lon"], "east": bbox["max_lon"],
        "south": bbox["min_lat"], "north": bbox["max_lat"],
    }
    return cropped, geo_bounds


def save_geotiff(img, bounds, out_path):
    """Save PIL image as GeoTIFF with WGS84 georeferencing."""
    if not RASTERIO_OK:
        # Fallback: save plain TIFF + world file
        img.save(out_path.replace(".tif", ".png"))
        _write_world_file(bounds, img.size,
                          out_path.replace(".tif", ".pgw"))
        return out_path.replace(".tif", ".png"), "PNG + world file (rasterio not available)"

    arr = np.array(img)                          # H×W×3
    transform = from_bounds(
        bounds["west"], bounds["south"],
        bounds["east"], bounds["north"],
        img.width, img.height
    )
    crs = CRS.from_epsg(4326)

    with rasterio.open(
        out_path, "w",
        driver="GTiff", height=img.height, width=img.width,
        count=3, dtype=arr.dtype,
        crs=crs, transform=transform,
        compress="lzw",
    ) as dst:
        for band in range(3):
            dst.write(arr[:, :, band], band + 1)
        dst.update_tags(
            AREA_OR_POINT="Area",
            TIFFTAG_SOFTWARE="Satellite GeoTIFF Capture — Uppata Analytics LLC",
            bounds=json.dumps(bounds),
        )
    return out_path, "GeoTIFF (EPSG:4326, LZW compressed)"


def _write_world_file(bounds, size, path):
    """Write .pgw / .jgw world file for georeferencing."""
    w, h = size
    px_w = (bounds["east"]  - bounds["west"])  / w
    px_h = (bounds["north"] - bounds["south"]) / h
    with open(path, "w") as f:
        f.write(f"{px_w}\n0.0\n0.0\n{-px_h}\n"
                f"{bounds['west']  + px_w/2}\n"
                f"{bounds['north'] - px_h/2}\n")


def format_bytes(n):
    if n < 1024:        return f"{n} B"
    if n < 1024**2:     return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.2f} MB"


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛰️ Satellite GeoTIFF Capture")
    st.markdown("---")

    st.markdown("### 📡 Tile Source")
    source_name = st.selectbox("Map source", list(TILE_SOURCES.keys()), index=0)
    src = TILE_SOURCES[source_name]

    st.markdown("### 🔍 Zoom Level")
    zoom = st.slider(
        "Zoom", min_value=10, max_value=src["max_zoom"],
        value=16, help="Higher zoom = more detail but more tiles"
    )

    st.markdown("### 📍 AOI Definition")
    aoi_mode = st.radio(
        "AOI method",
        ["Draw on map", "Enter coordinates"],
        horizontal=False
    )

    # Manual coordinate entry
    if aoi_mode == "Enter coordinates":
        st.markdown("**Bounding box (WGS84)**")
        col1, col2 = st.columns(2)
        with col1:
            min_lat = st.number_input("Min lat (S)", value=22.14, format="%.6f")
            min_lon = st.number_input("Min lon (W)", value=90.67, format="%.6f")
        with col2:
            max_lat = st.number_input("Max lat (N)", value=22.19, format="%.6f")
            max_lon = st.number_input("Max lon (E)", value=90.73, format="%.6f")
        manual_bbox = {"min_lat": min_lat, "max_lat": max_lat,
                       "min_lon": min_lon, "max_lon": max_lon}
    else:
        manual_bbox = None

    st.markdown("### 💾 Output")
    out_dir = st.text_input(
        "Save directory",
        value=os.path.join(os.getcwd(), "satellite_captures"),
        help="Absolute or relative path"
    )
    filename_prefix = st.text_input("Filename prefix", value="capture")
    add_timestamp = st.checkbox("Append timestamp", value=True)

    st.markdown("---")
    st.markdown(
        '<div class="info-box">📌 Draw a rectangle on the map, then click <b>Capture GeoTIFF</b>.<br><br>'
        '⚠️ Keep tile count under ~200 for fast results. Increase zoom for higher resolution.</div>',
        unsafe_allow_html=True
    )

    st.markdown("---")
    st.markdown(
        "**Uppata Analytics LLC**  \n"
        "Zia U. Ahmed, Ph.D.  \n"
        "🌐 [github.com/zia207](https://github.com/zia207)",
        unsafe_allow_html=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("# 🛰️ Satellite GeoTIFF Capture")
st.markdown(
    "Draw an AOI rectangle on the map → set zoom & source → click **Capture GeoTIFF** "
    "to download and save georeferenced satellite imagery."
)

tab_map, tab_preview, tab_log = st.tabs(["🗺️ Map & AOI", "🖼️ Preview & Export", "📋 Log"])

# ── BOUNDING BOX STATE ───────────────────────────────────────────────────────
if "bbox" not in st.session_state:
    # Default: Bhola District, Bangladesh
    st.session_state.bbox = {
        "min_lat": 22.14, "max_lat": 22.19,
        "min_lon": 90.67, "max_lon": 90.73,
    }
if "last_capture" not in st.session_state:
    st.session_state.last_capture = None
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_lines.append(f"[{ts}]  {msg}")

# ── TAB 1: MAP ───────────────────────────────────────────────────────────────
with tab_map:
    bbox = st.session_state.bbox if manual_bbox is None else manual_bbox

    center_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2
    center_lon = (bbox["min_lon"] + bbox["max_lon"]) / 2

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        tiles=None,
    )

    # Add chosen tile source
    folium.TileLayer(
        tiles=src["url"].replace("{x}", "{x}").replace("{y}", "{y}").replace("{z}", "{z}"),
        attr=src["attr"],
        name=source_name,
        max_zoom=src["max_zoom"],
    ).add_to(m)

    # AOI rectangle
    folium.Rectangle(
        bounds=[[bbox["min_lat"], bbox["min_lon"]], [bbox["max_lat"], bbox["max_lon"]]],
        color="#FFD700",
        weight=3,
        fill=True,
        fill_color="#FFD700",
        fill_opacity=0.12,
        tooltip="Current AOI",
    ).add_to(m)

    # AOI centre marker
    folium.Marker(
        [center_lat, center_lon],
        tooltip=f"AOI centre: {center_lat:.5f}, {center_lon:.5f}",
        icon=folium.Icon(color="red", icon="crosshairs", prefix="fa"),
    ).add_to(m)

    folium.LayerControl().add_to(m)

    map_data = st_folium(m, width="100%", height=540, returned_objects=["last_clicked", "bounds"])

    # Update bbox from map bounds if user panned/zoomed and mode is draw
    if aoi_mode == "Draw on map" and map_data and map_data.get("bounds"):
        b = map_data["bounds"]
        sw = b.get("_southWest", {})
        ne = b.get("_northEast", {})
        if sw and ne:
            # Shrink map viewport to 60% to simulate an AOI inside view
            lat_pad = (ne.get("lat",0) - sw.get("lat",0)) * 0.15
            lon_pad = (ne.get("lng",0) - sw.get("lng",0)) * 0.15
            new_bbox = {
                "min_lat": round(sw.get("lat",0) + lat_pad, 6),
                "max_lat": round(ne.get("lat",0) - lat_pad, 6),
                "min_lon": round(sw.get("lng",0) + lon_pad, 6),
                "max_lon": round(ne.get("lng",0) - lon_pad, 6),
            }
            st.session_state.bbox = new_bbox
            bbox = new_bbox

    # Override with manual if chosen
    if manual_bbox is not None:
        bbox = manual_bbox
        st.session_state.bbox = manual_bbox

    # ── AOI METRICS ──────────────────────────────────────────────────────────
    n_tiles = estimate_tile_count(bbox, zoom)
    lat_span = bbox["max_lat"] - bbox["min_lat"]
    lon_span = bbox["max_lon"] - bbox["min_lon"]
    # Approx metres at equator
    lat_m = lat_span * 111_320
    lon_m = lon_span * 111_320 * math.cos(math.radians(center_lat))
    area_km2 = (lat_m * lon_m) / 1_000_000

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="label">Tile count (zoom {zoom})</div>'
                    f'<div class="value">{n_tiles:,}</div></div>', unsafe_allow_html=True)
    with col2:
        est_px_w = int(lon_span / (360 / (2**zoom)) * 256)
        est_px_h = int(lat_span / (180 / (2**zoom)) * 256)
        st.markdown(f'<div class="metric-card"><div class="label">Est. output resolution</div>'
                    f'<div class="value">{est_px_w} × {est_px_h} px</div></div>',
                    unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="label">AOI area</div>'
                    f'<div class="value">{area_km2:.2f} km²</div></div>', unsafe_allow_html=True)
    with col4:
        est_mb = n_tiles * 0.04
        st.markdown(f'<div class="metric-card"><div class="label">Est. download</div>'
                    f'<div class="value">~{est_mb:.1f} MB</div></div>', unsafe_allow_html=True)

    if n_tiles > 400:
        st.warning(f"⚠️  {n_tiles} tiles is large — reduce zoom or shrink AOI for faster capture.")
    elif n_tiles > 150:
        st.info(f"ℹ️  {n_tiles} tiles — this will take ~{n_tiles*0.1:.0f}s with rate limiting.")

    st.markdown("---")

    # ── COORDINATE DISPLAY ────────────────────────────────────────────────────
    with st.expander("📐 AOI Coordinates", expanded=False):
        cc1, cc2 = st.columns(2)
        with cc1:
            st.code(
                f"min_lat (S) : {bbox['min_lat']:.6f}\n"
                f"max_lat (N) : {bbox['max_lat']:.6f}\n"
                f"min_lon (W) : {bbox['min_lon']:.6f}\n"
                f"max_lon (E) : {bbox['max_lon']:.6f}",
                language="text"
            )
        with cc2:
            st.code(
                f"Centre      : {center_lat:.6f}, {center_lon:.6f}\n"
                f"Lat span    : {lat_span:.6f}° ({lat_m:.0f} m)\n"
                f"Lon span    : {lon_span:.6f}° ({lon_m:.0f} m)\n"
                f"Zoom level  : {zoom}",
                language="text"
            )

    # ── CAPTURE BUTTON ────────────────────────────────────────────────────────
    st.markdown("###")
    cap_col1, cap_col2 = st.columns([2, 1])
    with cap_col1:
        do_capture = st.button("📥  Capture GeoTIFF", use_container_width=True)
    with cap_col2:
        clear_btn = st.button("🗑️  Clear Preview", use_container_width=True)
        if clear_btn:
            st.session_state.last_capture = None
            st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # CAPTURE LOGIC
    # ─────────────────────────────────────────────────────────────────────────
    if do_capture:
        if n_tiles > 600:
            st.error("❌  Too many tiles (>600). Reduce AOI or lower zoom.")
        else:
            os.makedirs(out_dir, exist_ok=True)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname  = f"{filename_prefix}_{ts_str}" if add_timestamp else filename_prefix
            out_path = os.path.join(out_dir, fname + ".tif")

            log(f"Starting capture — source: {source_name}, zoom: {zoom}, tiles: {n_tiles}")
            log(f"AOI: {bbox}")

            progress_bar = st.progress(0, text="Initialising…")
            status_txt   = st.empty()

            def update_progress(pct, msg):
                progress_bar.progress(pct, text=msg)
                status_txt.markdown(f"`{msg}`")

            with st.spinner("Fetching tiles…"):
                t0 = time.time()
                try:
                    img, geo_bounds = stitch_tiles(
                        bbox, zoom, src["url"],
                        tile_size=src["tile_size"],
                        progress_cb=update_progress,
                    )
                    elapsed = time.time() - t0
                    log(f"Stitched {n_tiles} tiles in {elapsed:.1f}s — image: {img.size[0]}×{img.size[1]} px")

                    progress_bar.progress(1.0, text="Saving GeoTIFF…")
                    saved_path, fmt = save_geotiff(img, geo_bounds, out_path)

                    # Also save PNG preview
                    png_path = saved_path.replace(".tif", ".png").replace(".png.png", ".png")
                    if not png_path.endswith(".png"):
                        png_path += ".png"
                    img.save(png_path)

                    # Metadata JSON
                    meta = {
                        "source"    : source_name,
                        "zoom"      : zoom,
                        "bbox"      : bbox,
                        "geo_bounds": geo_bounds,
                        "resolution": {"width": img.size[0], "height": img.size[1]},
                        "tiles"     : n_tiles,
                        "format"    : fmt,
                        "captured"  : ts_str,
                        "file"      : os.path.basename(saved_path),
                    }
                    meta_path = saved_path.replace(".tif", "_meta.json").replace(".png", "_meta.json")
                    with open(meta_path, "w") as mf:
                        json.dump(meta, mf, indent=2)

                    log(f"Saved → {saved_path} ({fmt})")
                    log(f"Preview PNG → {png_path}")
                    log(f"Metadata → {meta_path}")

                    st.session_state.last_capture = {
                        "img"       : img,
                        "path"      : saved_path,
                        "png_path"  : png_path,
                        "meta"      : meta,
                        "bounds"    : geo_bounds,
                        "fmt"       : fmt,
                        "elapsed"   : elapsed,
                    }

                    progress_bar.progress(1.0, text="✅  Done!")
                    st.success(f"✅  Saved to `{saved_path}`")

                except Exception as e:
                    log(f"ERROR: {e}")
                    st.error(f"❌  Capture failed: {e}")
                    progress_bar.empty()


# ── TAB 2: PREVIEW & EXPORT ──────────────────────────────────────────────────
with tab_preview:
    cap = st.session_state.last_capture
    if cap is None:
        st.info("🖼️  No capture yet — go to **Map & AOI** tab and click **Capture GeoTIFF**.")
    else:
        st.success(f"✅  Capture complete in {cap['elapsed']:.1f}s")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-card"><div class="label">Output format</div>'
                        f'<div class="value">{cap["fmt"].split("(")[0].strip()}</div></div>',
                        unsafe_allow_html=True)
        with c2:
            w, h = cap["img"].size
            st.markdown(f'<div class="metric-card"><div class="label">Image dimensions</div>'
                        f'<div class="value">{w} × {h} px</div></div>',
                        unsafe_allow_html=True)
        with c3:
            sz = os.path.getsize(cap["path"]) if os.path.exists(cap["path"]) else 0
            st.markdown(f'<div class="metric-card"><div class="label">File size</div>'
                        f'<div class="value">{format_bytes(sz)}</div></div>',
                        unsafe_allow_html=True)

        st.markdown("### 🖼️ Captured Image Preview")
        st.image(cap["img"], use_column_width=True,
                 caption=f"{source_name} — Zoom {cap['meta']['zoom']} — {w}×{h} px")

        # Download buttons
        st.markdown("### 📥 Download")
        dl1, dl2, dl3 = st.columns(3)

        with dl1:
            buf = io.BytesIO()
            cap["img"].save(buf, format="PNG")
            st.download_button("⬇️ Download PNG",
                               data=buf.getvalue(),
                               file_name=os.path.basename(cap["png_path"]),
                               mime="image/png",
                               use_container_width=True)
        with dl2:
            if os.path.exists(cap["path"]) and cap["path"].endswith(".tif"):
                with open(cap["path"], "rb") as f:
                    st.download_button("⬇️ Download GeoTIFF",
                                       data=f.read(),
                                       file_name=os.path.basename(cap["path"]),
                                       mime="image/tiff",
                                       use_container_width=True)
            else:
                st.caption("GeoTIFF not available")
        with dl3:
            st.download_button("⬇️ Download Metadata JSON",
                               data=json.dumps(cap["meta"], indent=2),
                               file_name=os.path.basename(cap["path"]).replace(".tif","_meta.json"),
                               mime="application/json",
                               use_container_width=True)

        # Georeferencing info
        st.markdown("### 🌍 Georeferencing")
        b = cap["bounds"]
        st.code(
            f"CRS        : EPSG:4326 (WGS84)\n"
            f"West  (lon): {b['west']:.6f}\n"
            f"East  (lon): {b['east']:.6f}\n"
            f"South (lat): {b['south']:.6f}\n"
            f"North (lat): {b['north']:.6f}\n"
            f"Pixel size : {(b['east']-b['west'])/w*111320:.2f} m/px (lon) × "
            f"{(b['north']-b['south'])/h*111320:.2f} m/px (lat)\n"
            f"File       : {cap['path']}",
            language="text"
        )

        # Metadata JSON viewer
        with st.expander("📄 Metadata JSON", expanded=False):
            st.json(cap["meta"])

        # QGIS usage tip
        with st.expander("🗺️ How to open in QGIS / ArcGIS", expanded=False):
            st.markdown("""
**QGIS:**
1. `Layer` → `Add Layer` → `Add Raster Layer`
2. Browse to the `.tif` file
3. CRS is already embedded as **EPSG:4326** — QGIS will read it automatically

**ArcGIS Pro:**
1. `Insert` → `Data` → `Add Data`
2. Select the `.tif` file
3. Right-click layer → `Properties` → verify coordinate system

**Python / rasterio:**
```python
import rasterio
with rasterio.open("capture.tif") as src:
    print(src.crs, src.bounds, src.transform)
    img = src.read()          # shape (3, H, W)
```

**Python / GDAL:**
```bash
gdalinfo capture.tif
gdal_translate -of GTiff capture.tif reprojected.tif -t_srs EPSG:3857
```
""")


# ── TAB 3: LOG ────────────────────────────────────────────────────────────────
with tab_log:
    if not st.session_state.log_lines:
        st.info("No activity yet.")
    else:
        for line in reversed(st.session_state.log_lines[-50:]):
            st.markdown(f"`{line}`")
        if st.button("Clear log"):
            st.session_state.log_lines = []
            st.rerun()
