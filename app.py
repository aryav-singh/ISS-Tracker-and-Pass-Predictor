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

st.set_page_config(
    page_title="ISS Tracker & Pass Predictor ",
    page_icon="🛰️",
    layout="wide" 
)

# Remove extra top padding and set font across the app
st.markdown("""
    <style>
        html, body, [class*="st-"], .stMarkdown, p, span, div, label, h1, h2, h3, h4, h5, h6 {
            font-family: "Calibri",  sans-serif !important;
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

st.markdown("<h1 style='text-align: center;'>ISS Live Tracker & Pass Predictor</h1>", unsafe_allow_html=True)

st.subheader("Live Tracker")

# Render live Leaflet iframe
st.session_state.iss_iframe_uri = tracker.render_live_iss_leaflet(iss_sat)
st.iframe(st.session_state.iss_iframe_uri, height=440)

st.subheader("Pass Predictor") 

# Select the ISS satellite directly without a dropdown widget
sat_name = "ISS (ZARYA)"
sat = sats.get(sat_name, list(sats.values())[0])

# Display it cleanly as text instead of a select box
st.text(f"Satellite: {sat_name}")

n_kozai = sat.model.no_kozai
period_min = 2 * math.pi / n_kozai

st.write("Search Location")

# Initialize session state for the selected location if it doesn't exist
if "selected_loc" not in st.session_state:
    st.session_state.selected_loc = None

has_searched = st.session_state.selected_loc is not None
placeholder_text = "Type a different city..." if has_searched else "Type a city"
widget_key = f"location_searchbox_{'searched' if has_searched else 'initial'}"

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
resolved_address = st.session_state.selected_loc["address"]
site_obj = wgs84.latlon(lat, lon)

st.success(f"📍 Selected: **{resolved_address}** (Lat: {lat:.2f}, Lon: {lon:.2f})")

min_alt = st.number_input(
    "Minimum Altitude (°)",
    min_value=0,
    max_value=90,
    value=10,
    step=1,
    placeholder="Maximum 90 degrees",
    help="Minimum elevation angle above the horizon for a valid pass."
)

days_to_search = st.number_input(
    "Days to Search",
    min_value=1,
    max_value=30,
    value=10,
    step=1,
    placeholder="Maximum 30 days",
    help="Number of future days to scan for satellite passes."
)

only_visible = st.checkbox("Only visible passes", value=True)

tz_name = get_tzf().timezone_at(lat=lat, lng=lon) or "UTC"
tz = ZoneInfo(tz_name)

passes = tracker.find_passes(sat, lat, lon, eph, days_to_search, min_alt)
filtered_passes = [p for p in passes if not (only_visible and not p["visible"])]

if not filtered_passes:
    st.info("No passes found for this location with current filters.")
    st.stop()

rows = []
for i, p in enumerate(filtered_passes):
    rows.append({
        "Pass Number": i+1,
        "Peak (local)": tracker.fmt_local(p["peak"], tz),
        "Peak (UTC)": tracker.fmt_utc(p["peak"]),
        "Maximum altitude (°)": round(p["max_alt"]),
        "Peak azimuth (°)": round(p["peak_az"]),
        "Duration (s)": round((p["set"] - p["rise"]) * 86400),
        "Sun altitude (°)": round(p["sun_alt"]),
    })

st.caption(f"Time zone: {tz_name} | TLE epoch: {tracker.fmt_utc(sat.epoch)}")
st.dataframe(rows)

st.markdown("---")
st.subheader("🛰️ Pass Visualization")

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
    f"**Local Peak Time:** {local_time_str}  \n"
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