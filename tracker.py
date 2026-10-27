# tracker.py - core satellite pass logic, with Plotly map support
import numpy as np 
import matplotlib.pyplot as plt 
from skyfield.api import load, wgs84 
import requests
import plotly.graph_objects as go
import urllib.request
import streamlit.components.v1 as components
import base64
from skyfield.api import wgs84
import time
import os
import socket
import streamlit as st

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"
TLE_NAME = "stations.tle" 
MAX_TLE_AGE_DAYS = 0.2
# Define twilight boundaries (civil/nautical twilight range)
SUN_LIMIT_UPPER = -6.0   # Upper bound: Civil twilight boundary (sky must be darker than this)
SUN_LIMIT_LOWER = -28.0  # Lower bound: Deepest allowable night sun altitude 



# --- FORCE IPv4 TO BYPASS WINDOWS TIMEOUT BUG (WinError 10060) ---
old_getaddrinfo = socket.getaddrinfo
def new_getaddrinfo(*args, **kwargs):
    responses = old_getaddrinfo(*args, **kwargs)
    return [r for r in responses if r[0] == socket.AF_INET]
socket.getaddrinfo = new_getaddrinfo
# -----------------------------------------------------------------

ts = load.timescale() 

ARISS_URL = "http://live.ariss.org/iss.txt"   # backup source: ISS only, on a different server from CelesTrak

def fetch_iss_tle_from_ariss():
    # Download the ISS TLE from ARISS and return it as 3-line TLE text (name, line 1, line 2)
    req = urllib.request.Request(ARISS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        text = response.read().decode("utf-8", errors="ignore")       # raw bytes to text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]    # drop blank lines
    line1 = next((ln for ln in lines if ln.startswith("1 25544")), None)   # ISS TLE line 1
    line2 = next((ln for ln in lines if ln.startswith("2 25544")), None)   # ISS TLE line 2
    if not line1 or not line2:
        raise ValueError("ARISS file did not contain an ISS TLE")
    return f"ISS (ZARYA)\n{line1}\n{line2}\n"                         # name line plus the two TLE lines

def load_satellites():
    # Re-download if the saved file is missing, empty, or older than the limit
    too_old = (not os.path.exists(TLE_NAME)
               or os.path.getsize(TLE_NAME) == 0
               or (time.time() - os.path.getmtime(TLE_NAME)) / 3600.0 > MAX_TLE_AGE_DAYS * 24)
    if too_old:
        try:
            req = urllib.request.Request(TLE_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as response:   # 20 s instead of 5 s
                data = response.read()
            # Sanity check: a real download contains many TLE entries
            if data.count(b"\n1 ") < 3:
                raise ValueError("download did not look like a TLE file")
            with open(TLE_NAME, "wb") as f:                            # only overwrite after the check passes
                f.write(data)
            print("Downloaded fresh TLE data from CelesTrak")
        except Exception as e:
            print(f"CelesTrak download FAILED: {e!r}")                # real reason shows in the terminal
            try:
                text = fetch_iss_tle_from_ariss()                     # try the backup source
                with open(TLE_NAME, "w") as f:                        # only write after the fetch succeeded
                    f.write(text)
                print("Using ISS-only TLE from ARISS instead")
            except Exception as e2:
                print(f"ARISS download FAILED too: {e2!r}")
                if not os.path.exists(TLE_NAME) or os.path.getsize(TLE_NAME) == 0:
                    raise RuntimeError("No TLE data available and both downloads failed") from e2
    return {s.name: s for s in load.tle_file(TLE_NAME)}

def get_tle_lines(name):
    # Read the saved TLE file and return (line1, line2) for the named satellite
    with open(TLE_NAME, "r") as f:
        lines = [ln.strip() for ln in f if ln.strip()]   # drop blank lines
    for i in range(0, len(lines) - 2, 3):                # each entry is 3 lines: name, line 1, line 2
        if lines[i].startswith(name):
            return lines[i + 1], lines[i + 2]
    return None, None




def search_locations(searchterm: str, value=None):
    # Require at least 3 characters to avoid spamming requests on every keystroke
    if not searchterm or len(str(searchterm).strip()) < 3:
        return []
    
    results = []
    try:
        api_key = st.secrets.get("LOCATIONIQ_API_KEY", "")
        if not api_key:
            print("LocationIQ error: No secrets found for API key.")
            return []
            
        url = "https://us1.locationiq.com/v1/search.php"
        params = {
            'key': api_key,
            'q': searchterm,
            'format': 'json',
            'limit': 5,
            'normalizecity': 1,
            'addressdetails': 1,
        }
        
        response = requests.get(url, params=params, timeout=3)
        
        if response.status_code == 429:
            print("LocationIQ error: Rate limit exceeded (429). Slow down typing.")
            return []
            
        if response.status_code == 200:
            data = response.json()
            for loc in data:
                lat = float(loc['lat'])
                lon = float(loc['lon'])
                
                addr_parts = loc.get('address', {})
                city = (
                    addr_parts.get('city') or 
                    addr_parts.get('town') or 
                    addr_parts.get('village') or 
                    addr_parts.get('municipality')
                )
                state = addr_parts.get('state')
                country = addr_parts.get('country')
                
                if city and state and country:
                    address = f"{city}, {state}, {country}"
                elif city and country:
                    address = f"{city}, {country}"
                else:
                    address = loc.get('display_name', '')
                
                if not address:
                    continue
                    
                item = {"lat": lat, "lon": lon, "address": address}
                if not any(r[0] == address for r in results):
                    results.append((address, item))
                
    except Exception as e:
        print(f"LocationIQ error: {e}")
        
    return results

def find_passes(sat, lat, lon, eph, days=10, min_alt=10.0):
    site = wgs84.latlon(lat, lon)
    t0 = ts.now()
    t1 = t0 + days
    times, events = sat.find_events(site, t0, t1, altitude_degrees=min_alt)
    observer = eph["earth"] + site
    
    SUN_LIMIT_UPPER = -6.0   
    SUN_LIMIT_LOWER = -28.0  
    
    passes = [] 
    current = {} 
    for t, e in zip(times, events):
        if e == 0: 
            current = {"rise": t}
        elif e == 1 and current: 
            alt, az, _ = (sat - site).at(t).altaz()
            current["peak"] = t
            current["max_alt"] = round(alt.degrees, 1)
            current["peak_az"] = round(az.degrees, 1)
        elif e == 2 and "peak" in current: 
            current["set"] = t
            
            # Sample across the entire pass window to catch valid rising/setting windows
            t_check = ts.linspace(current["rise"], current["set"], 30)
            sunlit_arr = sat.at(t_check).is_sunlit(eph)
            obs_at_t = observer.at(t_check)
            sun_alt_arr = obs_at_t.observe(eph["sun"]).apparent().altaz()[0].degrees
            
            visible_points = [
                bool(s and SUN_LIMIT_LOWER <= sa < SUN_LIMIT_UPPER) 
                for s, sa in zip(sunlit_arr, sun_alt_arr)
            ]
            
            peak_sun_alt = observer.at(current["peak"]).observe(eph["sun"]).apparent().altaz()[0].degrees
            
            current["sunlit"] = bool(sat.at(current["peak"]).is_sunlit(eph)) 
            current["sun_alt"] = round(peak_sun_alt, 1)
            
            # Must have valid visible points during the pass, 
            # AND the peak sun altitude cannot exceed our strict -28.0 floor
            current["visible"] = bool(
                any(visible_points) and 
                peak_sun_alt >= SUN_LIMIT_LOWER
            )
            
            passes.append(current)
            current = {}
            
    return passes

def visible_window(sat, eph, p, n=600):
    t_arr = ts.linspace(p["rise"], p["set"], 75)
    lit = sat.at(t_arr).is_sunlit(eph)
    idx = np.where(lit)[0] 
    if len(idx) == 0:
        return None 
    return t_arr[idx[0]], t_arr[idx[-1]]

def fmt_utc(t):
    return t.utc_strftime("%D, %H:%M:%S UTC")

def zone_label(local_dt):
    total_min = int(local_dt.utcoffset().total_seconds() // 60)
    sign = "+" if total_min >= 0 else "-"        
    h, m = divmod(abs(total_min), 60)            
    offset = f"UTC{sign}{h}" + (f":{m:02d}" if m else "")  
    abbr = local_dt.tzname() 
    
    # If abbr is a real alphabetic name (like EDT, EST), combine it with the offset
    if abbr and abbr.isalpha() and abbr not in ["UTC", "GMT"]:
        return f"{abbr}, {offset}"
    
    # Otherwise (for regions returning raw numbers like "+12"), just return the clean offset
    return offset

def fmt_local(t, tz):
    d = t.astimezone(tz) 
    return d.strftime("%D, %H:%M:%S ") + zone_label(d)



def plot_sky_path(sat, site_obj, site_name, p, eph):
    t_arr = ts.linspace(p["rise"], p["set"], 200)
    alt, az, _ = (sat - site_obj).at(t_arr).altaz()
    theta = np.radians(az.degrees)
    r = 90 - alt.degrees
    lit = sat.at(t_arr).is_sunlit(eph)

    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(1)

    # --- CLEAN WHITE BACKGROUND & GRIDS ---
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    
    # Configure grid lines for altitude/zenith and azimuth in dark gray for high contrast
    ax.grid(True, color=(0, 0, 0, 0.15), linestyle='--', linewidth=0.7)
    # -------------------------------------------

    ax.plot(theta, np.where(lit, np.nan, r), "--", color="gray", label="In Shadow (not visible)")
   # 1. "Sunlit (visible)" line styled blue to match the ground track Pass Window color ('blue')
    ax.plot(theta, np.where(lit, r, np.nan), "-", color="blue", label="Sunlit (visible)")
    
    ax.plot(theta[0], r[0], "go", label="Station Rise")
    ax.plot(theta[-1], r[-1], "ro", label="Station Set")
    
    i_peak = np.argmax(alt.degrees)
    
    # Add linestyle="None" so Matplotlib knows this is a marker-only plot and won't draw a line in the legend
    ax.plot(theta[i_peak], r[i_peak], marker="o", color="cyan", markersize=8, markeredgewidth=0.5, linestyle="None", label="Peak Position")

    lit_idx = np.where(lit)[0]
    if len(lit_idx) > 0 and lit_idx[0] > 0:
        # 3. Replaced yellow star with a magenta dot ("o", color="magenta") for "Exits shadow"
        ax.plot(theta[lit_idx[0]], r[lit_idx[0]], "o", color="magenta", markersize=6.5, label="Exits shadow")
    if len(lit_idx) > 0 and lit_idx[-1] < len(t_arr) - 1:
        ax.plot(theta[lit_idx[-1]], r[lit_idx[-1]], "o", color="darkorange", markersize=6.5, label="Enters shadow")

    ax.set_ylim(0, 90)
    ax.set_yticks([0, 30, 60, 90])
    ax.set_yticklabels(["90°", "60°", "30°", "0°"], color='black')
    ax.set_rlabel_position(135)
    
    ax.set_xticks(np.radians([0, 45, 90, 135, 180, 225, 270, 315]))
    ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"], color='black', fontweight='bold')
    
    # Style tick parameters and spine for white theme
    ax.tick_params(colors='black', labelsize=9)
    ax.spines['polar'].set_color('black')

   # Configure legend below the chart with labels visible, transparent background, and white text
    ax.legend(
        loc="upper center", 
        bbox_to_anchor=(0.5, -0.12), 
        ncol=3, 
        fontsize=8, 
        facecolor='none', 
        edgecolor='none', 
        labelcolor='black',
        frameon=False
    )
    plt.subplots_adjust(bottom=0.28)
    
    ax.set_title(f"ISS pass over {site_name}\nPeak Altitude: {p['max_alt']:.1f}°", fontsize=10, color='black', pad=15)
    
    return fig

def get_subsolar_point(eph, t):
    # Apparent position of the Sun as seen from Earth's center at time t
    astro = eph["earth"].at(t).observe(eph["sun"]).apparent()
    ra, dec, _ = astro.radec(epoch="date")                   # right ascension and declination of date
    lon = ((ra.hours - t.gast) * 15 + 540) % 360 - 180       # sub-solar longitude: RA minus sidereal time, wrapped to -180..180
    return dec.degrees, lon                                  # latitude, longitude in degrees

def get_day_night_polygon(eph, t):
    sun_lat, sun_lon = get_subsolar_point(eph, t)             # where the Sun is overhead at time t
    dec_rad = np.radians(sun_lat if abs(sun_lat) > 0.01 else 0.01)   # declination in radians; avoid dividing by zero at the equinox
    lons = np.linspace(-180, 180, 361)                        # boundary sampled every degree of longitude
    # Day/night boundary latitude at each longitude: tan(lat) = -cos(lon - sun_lon) / tan(declination)
    term_lats = np.degrees(np.arctan(-np.cos(np.radians(lons - sun_lon)) / np.tan(dec_rad)))
    term_lats = np.clip(term_lats, -89.9, 89.9)               # keep it on the map
    dark_pole = -90 if sun_lat >= 0 else 90                     # night lies toward the pole that is in darkness
    poly_lons = list(lons) + list(lons[::-1])                 # closed polygon: along the boundary, back along the pole
    poly_lats = list(term_lats) + [dark_pole] * len(lons)
    return poly_lons, poly_lats, list(lons), list(term_lats), sun_lat, sun_lon

def short_name(address):
    # Shorten a long geocoder address to City, State/Province, Country
    parts = [p.strip() for p in address.split(",")]
    if len(parts) <= 2:
        return address
    
    # Filter out postal codes (containing digits)
    filtered_parts = [p for p in parts if not any(char.isdigit() for char in p)]
    
    if len(filtered_parts) >= 3:
        city = filtered_parts[-3]
        state = filtered_parts[-2]
        country = filtered_parts[-1]
        return f"{city}, {state}, {country}"
    elif len(filtered_parts) == 2:
        return f"{filtered_parts[0]}, {filtered_parts[1]}"
        
    return f"{parts[0]}, {parts[-1]}"

def plot_plotly_ground_track(sat, lat, lon, site_name, p, period_min, eph=None):
    half = period_min / 2 / 1440
    
    t_orbit = ts.linspace(p["peak"] - half, p["peak"] + half, 600)
    t_pass = ts.linspace(p["rise"], p["set"], 200)

    sub_orbit = wgs84.subpoint_of(sat.at(t_orbit))
    sub_pass = wgs84.subpoint_of(sat.at(t_pass))
    sub_peak = wgs84.subpoint_of(sat.at(p["peak"]))

    def continuous_unwrap(lats, lons):
        new_lats, new_lons = [], []
        cumulative_offset = 0
        for i in range(len(lons)):
            if i > 0:
                diff = lons[i] - lons[i-1]
                if diff > 180:
                    cumulative_offset -= 360
                elif diff < -180:
                    cumulative_offset += 360
            new_lats.append(lats[i])
            new_lons.append(lons[i] + cumulative_offset)
        return new_lats, new_lons

    orbit_lats, orbit_lons = continuous_unwrap(sub_orbit.latitude.degrees, sub_orbit.longitude.degrees)
    pass_lats, pass_lons = continuous_unwrap(sub_pass.latitude.degrees, sub_pass.longitude.degrees)

    fig = go.Figure()

    # --- LIGHT NIGHT SHADING AND DAY/NIGHT BOUNDARY AT THE PEAK OF THE PASS ---
    if eph is not None and "peak" in p:
        poly_lons, poly_lats, curve_lons, curve_lats, _, _ = get_day_night_polygon(eph, p["peak"])
        for offset in [-360, 0, 360]:                           # three copies so the shading covers beyond +/-180 degrees
            fig.add_trace(go.Scattermap(
                lon=[x + offset for x in poly_lons], lat=poly_lats,
                mode="lines", fill="toself",                    # filled polygon; mode="lines" avoids dots at each vertex
                fillcolor="rgba(0, 8, 20, 0.15)", line=dict(width=0),   # light night shading, no outline
                showlegend=False, hoverinfo="skip"))               # keep out of legend and tooltips
            fig.add_trace(go.Scattermap(
                lon=[x + offset for x in curve_lons], lat=curve_lats,
                mode="lines", line=dict(color="black", width=2),   # day/night boundary line
                showlegend=False, hoverinfo="skip"))               # keep out of legend and tooltips
    # ------------------------------------------

    fig.add_trace(go.Scattermap(
        lat=orbit_lats,
        lon=orbit_lons,
        mode='lines',
        line=dict(width=2, color='orange'),
        name='Full Orbit',
        hovertemplate='<b>Full Orbit</b><br>Latitude: %{lat:.2f}°<br>Longitude: %{lon:.2f}°<extra></extra>'
    ))

    fig.add_trace(go.Scattermap(
        lat=pass_lats,
        lon=pass_lons,
        mode='lines',
        line=dict(width=4, color='blue'),
        name='Pass Window',
        hovertemplate='<b>Pass Window</b><br>Latitude: %{lat:.2f}°<br>Longitude: %{lon:.2f}°<extra></extra>'
    ))

    peak_lon = (sub_peak.longitude.degrees + 180) % 360 - 180
    fig.add_trace(go.Scattermap(
        lat=[sub_peak.latitude.degrees],
        lon=[peak_lon],
        mode='markers',
        marker=dict(size=10, color='cyan'),
        name='Peak Position',
        hovertemplate='<b>Peak Position</b><br>Latitude: %{lat:.2f}°<br>Longitude: %{lon:.2f}°<extra></extra>'
    ))

     # --- INTERNATIONAL DATE LINE TRACE (Magenta, placed at the end of the legend) ---
    idl_lats = list(range(-90, 91, 2))
    idl_lons = [180] * len(idl_lats)

    fig.add_trace(go.Scattermap(
        lat=idl_lats,
        lon=idl_lons,
        mode='lines',
        line=dict(width=1, color='maroon'),
        name='International Date Line',
        hovertemplate='<b>International Date Line</b><br>Longitude: 180°<extra></extra>'
    ))

    target_lon = (lon + 180) % 360 - 180                        # keep longitude in -180..180 for the map
    fig.add_trace(go.Scattermap(
        lat=[lat],
        lon=[target_lon],
        mode='markers',                                         # draw a dot
        marker=dict(size=12, color='red'),
        name=site_name,                                         # legend entry shows the full resolved address
        text=[site_name],                                         # same full address in the hover tooltip
        hovertemplate='<b>%{text}</b><br>Latitude: %{lat:.2f}°<br>Longitude: %{lon:.2f}°<extra></extra>'
    ))

    # -------------------------------------------------------------

    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(lat=lat, lon=target_lon),
            zoom=1.5
        ),
        legend=dict(
            orientation="h",                                 # entries laid out in a row
            x=0, xanchor="left",                             # start at the left edge
            y=-0.02, yanchor="top",                          # just below the map
            bgcolor="rgba(0, 0, 0, 0)",                      # transparent, matches page background
            font=dict(color="white", size=12),               # light text for dark page theme
        ),
        width=900,
        height=636,
        margin=dict(l=10, r=0, t=0, b=0),
    )

    return fig

def plot_live_iss_map(sat):
    # Get the exact current time
    t_now = ts.now()
    
    # Define a tight 90-minute window (45 min back, 45 min forward) to show current trajectory vector
    half_window = 0.03125  # ~45 minutes in days (90 min total orbit period)
    t_live_array = ts.linspace(t_now - half_window, t_now + half_window, 300)
    
    # Compute subpoints for the live trajectory and the exact current position
    sub_live = wgs84.subpoint_of(sat.at(t_live_array))
    sub_current = wgs84.subpoint_of(sat.at(t_now))

    def continuous_unwrap(lats, lons):
        """Cumulatively unwrap longitudes so the live trajectory stays continuous."""
        new_lats, new_lons = [], []
        cumulative_offset = 0
        for i in range(len(lons)):
            if i > 0:
                diff = lons[i] - lons[i-1]
                if diff > 180:
                    cumulative_offset -= 360
                elif diff < -180:
                    cumulative_offset += 360
            new_lats.append(lats[i])
            new_lons.append(lons[i] + cumulative_offset)
        return new_lats, new_lons

    live_lats, live_lons = continuous_unwrap(sub_live.latitude.degrees, sub_live.longitude.degrees)

    # Initialize the Plotly figure
    fig = go.Figure()

    # Add the live trajectory path segment
    fig.add_trace(go.Scattermap(
        lat=live_lats,
        lon=live_lons,
        mode='lines',
        line=dict(width=3, color='orange'),
        name='Current Trajectory',
        hovertemplate='<b>Trajectory</b><br>Latitude: %{lat:.2f}°<br>Longitude: %{lon:.2f}°<extra></extra>'
    ))

    # Normalize current longitude for display
    curr_lon = (sub_current.longitude.degrees + 180) % 360 - 180
    curr_lat = sub_current.latitude.degrees
    curr_alt_km = sub_current.elevation.km

    # Add a prominent marker for the ISS's exact current position
    fig.add_trace(go.Scattermap(
        lat=[curr_lat],
        lon=[curr_lon],
        mode='markers+text',
        marker=dict(size=14, color='green'),
        text=['ISS (Live)'],
        textposition="top right",
        name='Current Position',
        hovertemplate='<b>ISS Live Position</b><br>Latitude: %{lat:.2f}°<br>Longitude: %{lon:.2f}°<br>Altitude: ' + f'{curr_alt_km:.1f} km<extra></extra>'
    ))

    # Configure map layout centered precisely on the ISS's current coordinates
    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(lat=curr_lat, lon=curr_lon),
            zoom=2.5
        ),
        width=900,
        height=450,
        margin=dict(l=10, r=0, t=0, b=0),
    )

    return fig, curr_lat, curr_lon, curr_alt_km




def render_live_iss_leaflet(sat=None):
      # Look up the ISS entry in the saved TLE file (no hard-coded fallback)
    line1, line2 = get_tle_lines("ISS (ZARYA)")
    if not line1:
        raise RuntimeError("ISS not found in stations.tle")
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
        <style>
            body { 
                margin: 0; 
                padding: 0; 
                background: #000814; 
                overflow: hidden; 
                font-family: Calibri, sans-serif; 
            }
            #map { 
                width: 100%; 
                height: 420px; 
                border-radius: 8px; 
                background: #000814; 
            }
            .telemetry-overlay {
                position: absolute; top: 10px; right: 10px; z-index: 1000;
                background: rgba(0, 0, 0, 0.75); color: white; padding: 10px 15px;
                border-radius: 6px; font-family: monospace; font-size: 13px;
                pointer-events: none;
            }
            #error-banner {
                position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
                background: rgba(220, 53, 69, 0.9); color: white; padding: 15px 20px;
                border-radius: 6px; font-family: monospace; font-size: 14px; z-index: 2000;
                display: none; text-align: center; max-width: 80%;
            }
        </style>
        <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/satellite.js@4.0.0/dist/satellite.min.js"></script>
    </head>
    <body>
        <div style="position: relative;">
            <div id="map"></div>
            <div id="error-banner"></div>
            <div class="telemetry-overlay" id="telemetry">
                Initializing...
            </div>
        </div>

        <script>
            function showError(msg) {
                var b = document.getElementById('error-banner');
                b.style.display = 'block';
                b.innerHTML = "<b>Tracking Error:</b><br>" + msg;
                console.error(msg);
            }

            try {
                if (typeof L === 'undefined') {
                    throw new Error("Leaflet library failed to load.");
                }
                if (typeof satellite === 'undefined') {
                    throw new Error("Satellite.js library failed to load.");
                }

                var map = L.map('map', { 
                    zoomControl: true, 
                    worldCopyJump: false,
                    maxBounds: [[-85, -180], [85, 180]],
                    maxBoundsViscosity: 1.0,
                    minZoom: 2
                }).setView([0, 0], 3);

                L.tileLayer('https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png', {
                    maxZoom: 18,
                    attribution: '&copy; OpenStreetMap contributors'
                }).addTo(map);

                var terminatorLayer = L.layerGroup().addTo(map);

                function getSolarPosition(date) {
                    var jd = date.getTime() / 86400000 + 2440587.5;            // Julian date from the Unix time in ms
                    var n = jd - 2451545.0;                                    // days since J2000
                    var meanLon = (280.460 + 0.9856474 * n) % 360;             // Sun's mean longitude (deg)
                    var g = ((357.528 + 0.9856003 * n) % 360) * Math.PI / 180; // Sun's mean anomaly (rad)
                    var lambda = (meanLon + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * Math.PI / 180;  // ecliptic longitude (rad)
                    var eps = (23.439 - 0.0000004 * n) * Math.PI / 180;        // Earth's axial tilt (rad)
                    var ra = Math.atan2(Math.cos(eps) * Math.sin(lambda), Math.cos(lambda)) * 180 / Math.PI; // right ascension (deg)
                    var dec = Math.asin(Math.sin(eps) * Math.sin(lambda)) * 180 / Math.PI;                  // declination (deg)
                    var gmst = (280.46061837 + 360.98564736629 * n) % 360;     // Greenwich sidereal angle (deg)
                    var lon = ((((ra - gmst) % 360) + 540) % 360) - 180;       // sub-solar longitude, east positive, -180..180
                    return { lat: dec, lon: lon };                             // where the Sun is overhead
                }

                // Draw the night shading and the day/night boundary line for a given moment
                function updateTerminator(date) {
                    terminatorLayer.clearLayers();                    // remove the previous shading and line
                    var sun = getSolarPosition(date);                 // where the Sun is overhead right now
                    var sunLat = sun.lat;
                    if (Math.abs(sunLat) < 0.01) sunLat = 0.01;       // avoid dividing by zero at the equinoxes
                    var sunLon = sun.lon;
                    var decRad = sunLat * Math.PI / 180;              // declination in radians

                    // Latitude of the day/night boundary at one longitude with safety clipping
                    function terminatorLat(lon) {
                        var deltaLon = (lon - sunLon) * Math.PI / 180;
                        var decRad = sunLat * Math.PI / 180;
                        
                        // Prevent division by zero near equinoxes or extreme solstices
                        var tanDec = Math.tan(decRad);
                        if (Math.abs(tanDec) < 1e-5) tanDec = 1e-5;

                        var tanVal = -Math.cos(deltaLon) / tanDec;
                        var lat = Math.atan(tanVal) * 180 / Math.PI;
                        
                        // Fallback if NaN or Infinity is produced during extreme seasons
                        if (isNaN(lat) || !isFinite(lat)) {
                            lat = (sunLat >= 0) ? 89.9 : -89.9;
                        }
                        
                        return Math.max(-89.9, Math.min(89.9, lat));
                    }

                    // Night lies toward whichever pole is currently in darkness
                    var darkPole = sunLat >= 0 ? -90 : 90;

                    [-360, 0, 360].forEach(function(offset) {         // three copies so the shading wraps with the map
                        var curve = [];                               // boundary points as [lat, lon]
                        for (var lon = -180; lon <= 180; lon += 2) {
                            curve.push([terminatorLat(lon), lon + offset]);
                        }
                        var shade = curve.slice();                    // night polygon: the boundary, then along the dark pole
                        shade.push([darkPole, 180 + offset]);
                        shade.push([darkPole, -180 + offset]);

                        L.polygon(shade, { color: 'transparent', fillColor: '#000814', fillOpacity: 0.45, interactive: false }).addTo(terminatorLayer);  // night
                        L.polyline(curve, { color: '#000000', weight: 2, opacity: 0.9, interactive: false }).addTo(terminatorLayer);  // boundary line
                    });
                    return sun;                                         // lets the caller display the Sun's position
                }

                //--- ADDED CONTINUOUS UNWRAP HELPER TO FIX REFERENCE ERROR ---
                function continuousUnwrap(points) {
                    var newPoints = [];
                    var cumulativeOffset = 0;
                    for (var i = 0; i < points.length; i++) {
                        var lat = points[i][0];
                        var lon = points[i][1];
                        if (i > 0) {
                            var diff = lon - points[i-1][1];
                            if (diff > 180) {
                                cumulativeOffset -= 360;
                            } else if (diff < -180) {
                                cumulativeOffset += 360;
                            }
                        }
                        newPoints.push([lat, lon + cumulativeOffset]);
                    }
                    return newPoints;
                }
                // -------------------------------------------------------------

                var tleLine1 = "LINE1_PLACEHOLDER";
                var tleLine2 = "LINE2_PLACEHOLDER";
                var satrec = satellite.twoline2satrec(tleLine1, tleLine2);

                var issIcon = L.divIcon({
                    html: '<div style="font-size: 24px; text-align: center; transform: translate(-12px, -12px);">🛰️</div>',
                    className: 'iss-marker-icon'
                });

                var markerLeft = L.marker([0, 0], { icon: issIcon }).addTo(map);
                var markerCenter = L.marker([0, 0], { icon: issIcon }).addTo(map);
                var markerRight = L.marker([0, 0], { icon: issIcon }).addTo(map);

                var trajectoryGroup = L.layerGroup().addTo(map);
                var centeredOnce = false;

                function updatePosition() {
                    try {
                        var d = new Date();
                        var utcNow = new Date(Date.UTC(
                            d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
                            d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds()
                        ));

                        var sun = updateTerminator(utcNow);   // draw the shading and keep the Sun's position

                        var positionAndVelocity = satellite.propagate(satrec, utcNow);
                        if (!positionAndVelocity.position) return;

                        var gmst = satellite.gstime(utcNow);
                        var positionGd = satellite.eciToGeodetic(positionAndVelocity.position, gmst);
                        
                        var lat = satellite.degreesLat(positionGd.latitude);
                        var rawLon = satellite.degreesLong(positionGd.longitude);
                        var lon = (rawLon + 180) % 360 - 180;
                        var alt = positionGd.height;

                        markerLeft.setLatLng([lat, lon - 360]);
                        markerCenter.setLatLng([lat, lon]);
                        markerRight.setLatLng([lat, lon + 360]);

                        document.getElementById('telemetry').innerHTML =
                            `Latitude: ${lat.toFixed(2)}° | Longitude: ${lon.toFixed(2)}° | Altitude: ${alt.toFixed(1)} km`

                        if (!centeredOnce) {
                            map.setView([lat, lon], 3);
                            centeredOnce = true;
                        }

                        trajectoryGroup.clearLayers();
                        var currentSegment = [];

                        for (var i = 0; i <= 75; i += 1) {
                            var targetTime = new Date(utcNow.getTime() + i * 60000);
                            var pv = satellite.propagate(satrec, targetTime);
                            if (pv.position) {
                                var g = satellite.eciToGeodetic(pv.position, satellite.gstime(targetTime));
                                var pLat = satellite.degreesLat(g.latitude);
                                var pLon = satellite.degreesLong(g.longitude);
                                currentSegment.push([pLat, pLon]);
                            }
                        }

                        if (currentSegment.length > 0) {
                            var cleanSeg = continuousUnwrap(currentSegment);
                            var segLeft = cleanSeg.map(pt => [pt[0], pt[1] - 360]);
                            var segCenter = cleanSeg;
                            var segRight = cleanSeg.map(pt => [pt[0], pt[1] + 360]);

                            L.polyline(segLeft, { color: 'orange', weight: 2, opacity: 0.5 }).addTo(trajectoryGroup);
                            L.polyline(segCenter, { color: 'orange', weight: 2, opacity: 0.5 }).addTo(trajectoryGroup);
                            L.polyline(segRight, { color: 'orange', weight: 2, opacity: 0.5 }).addTo(trajectoryGroup);
                        }
                    } catch (innerErr) {
                        console.error(innerErr);
                    }
                }

                updatePosition();
                setInterval(updatePosition, 1000);

            } catch (err) {
                showError(err.message);
            }
        </script>
    </body>
    </html>
    """
    
    html_content = html_template.replace("LINE1_PLACEHOLDER", line1).replace("LINE2_PLACEHOLDER", line2)
    b64_encoded = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
    return f"data:text/html;base64,{b64_encoded}"