# app.py - Streamlit front end for the satellite pass predictor
import streamlit as st 
from skyfield.api import load, wgs84 
from timezonefinder import TimezoneFinder 
from zoneinfo import ZoneInfo 
import math
from streamlit_searchbox import st_searchbox 
import tracker
import time
import streamlit.components.v1 as components 
from datetime import datetime

st.set_page_config(
    page_title="LIVE ISS Tracker & Pass Predictor",
    page_icon="🛰️",
    layout="wide" 
)

# Remove extra top padding and set font across text elements without breaking icon fonts
st.markdown("""
    <style>
        /* Apply custom font ONLY to general text elements, avoiding Streamlit icon fonts */
        html, body, .stMarkdown, p, label, h1, h2, h3, h4, h5, h6 {
            font-family: "Calibri", sans-serif !important;
        }
        
        /* Ensure Streamlit internal icons retain their icon font family */
        [data-testid="stIconMaterial"], [class*="stIcon"] {
            font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
        }

        .block-container {
            padding-top: 1rem !important;
        }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource(ttl=6 * 3600) 
def get_satellites():
    return tracker.load_satellites()

@st.cache_resource 
def get_ephemeris():
    return load("de421.bsp")

@st.cache_resource 
def get_tzf():
    return TimezoneFinder()

# Load satellites and ephemeris safely (handled once)
try:
    sats = get_satellites()
except Exception as e:
    st.error(f"Could not load orbit data: {e}. Save the CelesTrak TLE text as stations.tle "
             "in the project folder, then reload this page.")
    st.stop() 

eph = get_ephemeris()

# Default to ISS for the live tracker view
iss_sat = sats.get("ISS (ZARYA)", list(sats.values())[0])

# Custom styling for a thicker border around the title box
st.markdown(
    """
    <style>
    .thick-border-box {
        border: 4px solid white; /* Adjust thickness (e.g., 3px) and color here */
        border-radius: 0.5rem;
        padding: 1rem;
        text-align: center;
    }
    </style>
    <div class="thick-border-box">
        <h1 style='margin: 0;'>LIVE ISS TRACKER & PASS PREDICTOR</h1>
    </div>
    """,
    unsafe_allow_html=True
)

st.subheader("Live Tracker")

# Render live Leaflet iframe cleanly without extra wrappers
st.session_state.iss_iframe_uri = tracker.render_live_iss_leaflet(iss_sat)
st.iframe(st.session_state.iss_iframe_uri, height=440)

# --- TLE FILE VIEWER ---
with st.expander("View Source Data"):
    try:
        with open("satellites.tle", "r") as f:
            st.code(f.read(), language="text")
    except FileNotFoundError:
        try:
            with open("stations.tle", "r") as f:
                st.code(f.read(), language="text")
        except Exception:
            st.code(f"ISS (ZARYA)\n{iss_sat.model.tle[0]}\n{iss_sat.model.tle[1]}", language="text")

st.markdown("<br>", unsafe_allow_html=True)

# Select the ISS satellite directly without a dropdown widget
sat_name = "ISS (ZARYA)"
sat = sats.get(sat_name, list(sats.values())[0])

st.subheader(f"Pass Predictor: {sat_name}") 


n_kozai = sat.model.no_kozai
period_min = 2 * math.pi / n_kozai

# Option to choose between city search or manual coordinates
input_mode = st.radio("Location Input Method", ["Search by City", "Enter Manual Coordinates"], horizontal=True, label_visibility="collapsed")

if input_mode == "Search by City":
    st.markdown("**Search Location:**")

    # Initialize session state for the selected location if it doesn't exist
    if "selected_loc" not in st.session_state:
        st.session_state.selected_loc = None

    has_searched = st.session_state.selected_loc is not None
    placeholder_text = "Type a different city..." if has_searched else "Type a city"
    widget_key = f"location_searchbox_{'searched' if has_searched else 'initial'}"

    # Full-width searchbox spanning the entire page container
    search_result = st_searchbox(
        tracker.search_locations,
        placeholder=placeholder_text,
        clear_on_submit=True,
        key=widget_key
    )

    if search_result and search_result != st.session_state.selected_loc:
        st.session_state.selected_loc = search_result

    if not st.session_state.selected_loc:
        st.info("Start typing a city name above to search for passes...")
        st.stop()

    lat = st.session_state.selected_loc["lat"]
    lon = st.session_state.selected_loc["lon"]
    resolved_address = tracker.short_name(st.session_state.selected_loc["address"])

else:
    st.markdown("**Enter Coordinates:**")
    col_lat, col_lon = st.columns(2)
    with col_lat:
        lat = st.number_input("Latitude (°)", min_value=-90.0, max_value=90.0, value=None, step=0.01, format="%.4f", placeholder="e.g. 43.65")
    with col_lon:
        lon = st.number_input("Longitude (°)", min_value=-180.0, max_value=180.0, value=None, step=0.01, format="%.4f", placeholder="e.g. -79.38")
    
    if lat is None or lon is None:
        st.info("Please enter both latitude and longitude coordinates above...")
        st.stop()
    
    resolved_address = f"Custom Coordinates ({lat:.2f}°, {lon:.2f}°)"

site_obj = wgs84.latlon(lat, lon)

st.success(f"📍 Selected: **{resolved_address}** (Lat: {lat:.2f}, Lon: {lon:.2f})")

min_alt = st.number_input(
    "Minimum Altitude (°)",
    min_value=0,
    max_value=90,
    value=10,
    step=1,
    placeholder="Maximum 90 degrees",
    help="Minimum elevation angle above the horizon to count as a visible pass."
)

days_to_search = st.number_input(
    "Days to Search",
    min_value=1,
    max_value=30,
    value=10,
    step=1,
    placeholder="Maximum 30 days, greater than 7 days are subject to significant inaccuracies",
    help="Number of future days to scan for satellite passes."
)

only_visible = st.checkbox("Only visible passes", value=True)

tz_name = get_tzf().timezone_at(lat=lat, lng=lon) or "UTC"
tz = ZoneInfo(tz_name)

passes = tracker.find_passes(sat, lat, lon, eph, days_to_search, min_alt)

# Filter passes while preserving their true absolute index from the full list
passes = tracker.find_passes(sat, lat, lon, eph, days_to_search, min_alt)

filtered_passes = []
rows = []
pass_indices = {}

for absolute_idx, p in enumerate(passes):
    if only_visible and not p["visible"]:
        continue
    
    filtered_passes.append(p)
    pass_num = absolute_idx + 1
    
    rows.append({
        "Pass Number": pass_num,
        "Peak (local)": tracker.fmt_local(p["peak"], tz),
        "Peak (UTC)": tracker.fmt_utc(p["peak"]),
        "Maximum altitude (°)": round(p["max_alt"]),
        "Peak azimuth (°)": round(p["peak_az"]),
        "Duration (s)": round((p["set"] - p["rise"]) * 86400),
        "Sun altitude (°)": round(p["sun_alt"]),
    })
    
    label = f"Pass #{pass_num} — Peak: {tracker.fmt_local(p['peak'], tz)} (Max Altitude: {round(p['max_alt'])}°)"
    pass_indices[label] = len(filtered_passes) - 1

if not filtered_passes:
    st.info("No passes found for this location with current filters.")
    st.stop()

rows = []
for i, p in enumerate(filtered_passes):
    rows.append({
        "Pass Number": i+1,
        "Peak (local)": tracker.fmt_local(p["peak"], tz),
        "Peak (UTC)": tracker.fmt_utc(p["peak"]),
        "Maximum altitude (°)": round(p["max_alt"], 1),
        "Peak azimuth (°)": round(p["peak_az"], 1),
        "Duration (s)": round((p["set"] - p["rise"]) * 86400),
        "Sun altitude (°)": round(p["sun_alt"], 1),
    })


tz_full_names = {
    "EDT": "Eastern Daylight Time (EDT)",
    "EST": "Eastern Standard Time (EST)",
    "CDT": "Central Daylight Time (CDT)",
    "CST": "Central Standard Time (CST)",
    "MDT": "Mountain Daylight Time (MDT)",
    "MST": "Mountain Standard Time (MST)",
    "PDT": "Pacific Daylight Time (PDT)",
    "PST": "Pacific Standard Time (PST)",
    "AKDT": "Alaska Daylight Time (AKDT)",
    "AKST": "Alaska Standard Time (AKST)",
    "HST": "Hawaii Standard Time (HST)",
    "BST": "British Summer Time (BST)",
    "GMT": "Greenwich Mean Time (GMT)",
    "UTC": "Coordinated Universal Time (UTC)",
    "WET": "Western European Time (WET)",
    "WEST": "Western European Summer Time (WEST)",
    "CET": "Central European Time (CET)",
    "CEST": "Central European Summer Time (CEST)",
    "EET": "Eastern European Time (EET)",
    "EEST": "Eastern European Summer Time (EEST)",
    "MSK": "Moscow Time (MSK)",
    "IST": "Indian Standard Time (IST)",
    "CST_CN": "China Standard Time (CST_CN)",
    "JST": "Japan Standard Time (JST)",
    "KST": "Korea Standard Time (KST)",
    "AEST": "Australian Eastern Standard Time (AEST)",
    "AEDT": "Australian Eastern Daylight Time (AEDT)",
    "ACST": "Australian Central Standard Time (ACST)",
    "ACDT": "Australian Central Daylight Time (ACDT)",
    "AWST": "Australian Western Standard Time (AWST)",
    "NZST": "New Zealand Standard Time (NZST)",
    "NZDT": "New Zealand Daylight Time (NZDT)",
    "BRT": "Brasilia Time (BRT)",
    "ART": "Argentina Time (ART)",
    "SAST": "South Africa Standard Time (SAST)",
    "GST": "Gulf Standard Time (GST)"
}

sample_local_time = datetime.now(tz)
abbr = sample_local_time.tzname() or ""

total_min = int(sample_local_time.utcoffset().total_seconds() // 60)
sign = "+" if total_min >= 0 else "-"          
h, m = divmod(abs(total_min), 60)            
offset_str = f"UTC{sign}{h}" + (f":{m:02d}" if m else "")

# Only use text names if abbr is genuinely alphabetic (like EDT, EST, BST)
if abbr and abbr.isalpha() and abbr not in ["UTC"]:
    full_zone_name = tz_full_names.get(abbr, abbr)
    clean_tz = f"{full_zone_name}, {offset_str}"
else:
    clean_tz = offset_str

st.caption(f"Time zone: {clean_tz} | Data updated on {tracker.fmt_utc(sat.epoch)}")
st.dataframe(rows, use_container_width=True)

st.markdown("---")
st.subheader("Pass Visualization")

# Pass selection mapping with a stable key so your choice persists
pass_indices = {f"Pass #{i+1} — Peak: {tracker.fmt_local(p['peak'], tz)} (Max Altitude: {round(p['max_alt'])}°)": i for i, p in enumerate(filtered_passes)}
selected_label = st.selectbox("Select a pass to plot", list(pass_indices.keys()), key="pass_selector")
selected_pass_idx = pass_indices[selected_label]
selected_pass = filtered_passes[selected_pass_idx]

st.markdown("<br>", unsafe_allow_html=True)

local_time_str = tracker.fmt_local(selected_pass['peak'], tz)
utc_time_str = tracker.fmt_utc(selected_pass['peak'])

st.markdown(
    f"### Pass #{selected_pass_idx+1} — {resolved_address}  \n"
    f"**Local Peak Time: {local_time_str}**  \n"
    f"**UTC Peak Time: {utc_time_str}** "
)

st.markdown("<br>", unsafe_allow_html=True)

col1, col2 = st.columns([1.25, 2.75])

with col1:
    st.subheader("Sky Chart (Looking Up)")
    fig_sky = tracker.plot_sky_path(sat, site_obj, resolved_address, selected_pass, eph)
    st.pyplot(fig_sky)

with col2:
    st.subheader("Interactive Ground Track Map")
    fig_map = tracker.plot_plotly_ground_track(sat, lat, lon, resolved_address, selected_pass, period_min, eph=eph)
    st.plotly_chart(fig_map)