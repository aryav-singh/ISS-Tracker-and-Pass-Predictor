# TODO: validate the next 3 visible passes against Heavens-Above (same day, same TLE epoch), then write README.md

import math  # for pi, used in the orbital period check
#from zoneinfo import ZoneInfo  # converts UTC times to Toronto time

import numpy as np                # for converting angles to radians
import matplotlib.pyplot as plt   # for plotting

# load = download/cache data, wgs84 = model of Earth's shape for lat/lon points
from skyfield.api import load, wgs84

def to_zulu(t):
    # Format a Skyfield time as a Zulu (UTC) string, 24-hour clock, e.g. "Mon Oct 26 06:49:12Z"
    return t.utc_strftime("%a %b %d %H:%M:%S UTC")

def zone_label(local_dt):
    # Offset from UTC as a timedelta, converted to whole minutes
    total_min = int(local_dt.utcoffset().total_seconds() // 60)
    sign = "+" if total_min >= 0 else "-"        # ahead of or behind UTC
    h, m = divmod(abs(total_min), 60)            # split into hours and leftover minutes
    offset = f"UTC{sign}{h}" + (f":{m:02d}" if m else "")  # e.g. "UTC+12", "UTC-4", "UTC+5:30"
    abbr = local_dt.tzname()                     # e.g. "EDT", or "+12" where there is no abbreviation
    # Include the abbreviation only when it is letters (EDT, JST), since "+12" would repeat the offset
    return f"{abbr}, {offset}" if abbr and abbr[0].isalpha() else offset

def to_local(t):
    # Convert a Skyfield time to the site's local time, e.g. "Thu Oct 29 19:11:13 UTC+12"
    local_dt = t.astimezone(local_tz)            # same moment, expressed in the site's time zone
    return local_dt.strftime("%a %b %d %H:%M:%S ") + zone_label(local_dt)

import cartopy.crs as ccrs                          # map projections (coordinate systems)
import cartopy.feature as cfeature                  # coastlines, borders, and so on
from cartopy.feature.nightshade import Nightshade   # shades the night side of Earth

from zoneinfo import ZoneInfo               # converts UTC times to a named time zone
from timezonefinder import TimezoneFinder   # looks up the time zone name from lat/lon

# ---------- Step 1: timescale and satellite data ----------

# Timescale object: needed to create precise times (Earth's rotation matters)
ts = load.timescale()

# Local filename where the downloaded TLE data is saved
tle_name = "stations.tle"
# Where the data comes from (CelesTrak's space stations group)
tle_url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"
# Re-download if the saved file is older than this many days
MAX_TLE_AGE_DAYS = 2.0

# Download if the file doesn't exist yet, or if it's older than the limit
if not load.exists(tle_name) or load.days_old(tle_name) > MAX_TLE_AGE_DAYS:
    load.download(tle_url, filename=tle_name)

# Load the satellites from the saved file
sats = load.tle_file(tle_name)

# Show how many satellites loaded, and the first few names (to check the ISS name)
print(len(sats), "satellites loaded")
print([s.name for s in sats][:5])

# ---------- Step 2: pick the ISS and check data freshness ----------

# Dictionary mapping each satellite's name to its object, for lookup by name
by_name = {s.name: s for s in sats}

# Grab the ISS (the name must match exactly; change it if you get a KeyError)
iss = by_name["ISS (ZARYA)"]

# Current time
now = ts.now()

# The TLE epoch is the moment the orbit data is valid for, in Zulu time
print("TLE epoch:", to_zulu(iss.epoch))

# Age of the data in days (older TLEs give less accurate predictions)
print("TLE age (days):", round(now - iss.epoch, 2))

# ---------- Step 3: sanity-check the orbital period ----------

# Mean motion n in radians per minute, read from the TLE
n = iss.model.no_kozai

# One orbit is 2*pi radians, so the period is 2*pi / n (in minutes)
period_min = 2 * math.pi / n

# Should be about 92-93 minutes; compare with your hand calculation
print(f"Orbital period: {period_min:.1f} min")

# ---------- Step 4: observer location and pass search ----------

# ---------- Observer location: change these three lines for any city ----------
SITE_NAME = "Suva, Fiji"   # label used in plots and printouts
SITE_LAT = -18.14 # degrees north (negative = south)
SITE_LON = 178.44    # degrees east (negative = west)

# Observer as a point on Earth's surface
site = wgs84.latlon(SITE_LAT, SITE_LON)

# Look up the time zone name for the site, e.g. "America/Toronto" (None if over open ocean)
tz_name = TimezoneFinder().timezone_at(lat=SITE_LAT, lng=SITE_LON) or "UTC"
# Time zone object that knows the daylight saving rules for that place
local_tz = ZoneInfo(tz_name)

# Search window: from now until 3 days from now
t0 = now

# How many days ahead to search for passes
SEARCH_DAYS = 10

# End of the search window
t1 = t0 + SEARCH_DAYS  # adding a number to a Skyfield time adds that many days

# Find every rise, peak, and set where the ISS is above 10 degrees elevation
times, events = iss.find_events(site, t0, t1, altitude_degrees=10.0)


# If nothing rises above the threshold in the search window, say so instead of crashing later
# If nothing rises above the threshold in the search window, say so instead of crashing later
if len(times) == 0:
    print(f"No passes above 10 degrees over {SITE_NAME} in the next {SEARCH_DAYS} days.")
    raise SystemExit  # stop the script here

# ---------- Step 5: print the results ----------



#local = ZoneInfo("America/Toronto")  # Toronto time zone (handles daylight saving)


passes = []    # will hold one dictionary per pass
current = {}   # the pass currently being built

for t, e in zip(times, events):
    if e == 0:  # rise: start a new pass
        current = {"rise": t}
    elif e == 1 and current:  # peak: record the time, elevation, and azimuth
        alt, az, _ = (iss - site).at(t).altaz()
        current["max_alt"] = alt.degrees   # highest elevation of this pass
        current["peak_az"] = az.degrees    # compass direction at the peak (0 = north, 90 = east)
        current["peak"] = t                # time of the peak
    elif e == 2 and current:  # set: finish the pass and save it
        current["set"] = t
        passes.append(current)
        current = {}

for p in passes:
    rise_zulu = to_zulu(p["rise"])  # convert UTC to Toronto time
    duration = (p["set"] - p["rise"]) * 86400  # time difference is in days, so convert to seconds
    # Zulu time first, then the same moment in local time
    print(rise_zulu, f"({to_local(p['rise'])})", f"max {p['max_alt']:.0f} deg", f"{duration:.0f} s")

eph = load("de421.bsp")  # planetary positions, needed to know where the Sun is (downloads once)

# Sun must be at least this many degrees below the horizon for a dark enough sky
SUN_LIMIT = -6.0

# Your position as a point on Earth, needed to compute where the Sun appears
observer = eph["earth"] + site

visible = []  # passes that meet all the visibility conditions

for p in passes:
    t_peak = p["peak"]  # check conditions at the moment of the peak

    # Condition 1: the ISS is in sunlight (not in Earth's shadow)
    sunlit = iss.at(t_peak).is_sunlit(eph)

    # Condition 2: the Sun's altitude as seen from the site (negative = below horizon)
    sun_alt = observer.at(t_peak).observe(eph["sun"]).apparent().altaz()[0].degrees

    # DEBUG: show why each pass passes or fails, in Zulu and local time (delete when done)
    print(to_zulu(t_peak), f"({to_local(t_peak)})", f"max {p['max_alt']:.0f} deg",
          "sunlit" if sunlit else "in shadow", f"sun {sun_alt:.0f} deg")

    # Keep only passes where the ISS is lit AND your sky is dark
    if sunlit and sun_alt < SUN_LIMIT:
        p["sun_alt"] = sun_alt  # remember it for printing
        visible.append(p)

def visible_window(p):
    # 600 evenly spaced times from rise to set (about 0.5 s apart)
    t_arr = ts.linspace(p["rise"], p["set"], 600)
    # Boolean array: True wherever the ISS is in sunlight (not in Earth's shadow)
    lit = iss.at(t_arr).is_sunlit(eph)
    # Indices of the samples where the ISS is lit
    idx = np.where(lit)[0]
    if len(idx) == 0:
        return None  # the ISS is in shadow for the whole pass
    # First and last lit samples: shadow exit, and the last lit moment above 10 degrees
    return t_arr[idx[0]], t_arr[idx[-1]]

# Print the visible passes in Zulu and local time
print(f"\n{len(visible)} visible passes in the next {SEARCH_DAYS} days over {SITE_NAME}:")
print()

for p in visible:
    window = visible_window(p)           # (start, end) of the lit part of the pass
    if window is None:
        continue                          # skip passes that are never lit
    start, end = window                   # first and last sunlit moments
    # Sky positions of the ISS at the start and end of the visible window
    alt_s, az_s, _ = (iss - site).at(start).altaz()
    alt_e, az_e, _ = (iss - site).at(end).altaz()
    lit_seconds = (end - start) * 86400   # days to seconds

    # Window starts within 1 s of the rise: the ISS was already sunlit when it rose
    lit_at_rise = (start - p["rise"]) * 86400 < 1
    # Window ends within 1 s of the set: the ISS stays sunlit until it sets
    lit_at_set = (p["set"] - end) * 86400 < 1
    start_label = "lit at rise" if lit_at_rise else "exits shadow"       # morning passes exit shadow
    end_label = "lit until set" if lit_at_set else "enters shadow"       # evening passes enter shadow

    # Line 1: peak time in UTC and local, peak elevation and azimuth, and the Sun's elevation
    print(to_zulu(p["peak"]), f"({to_local(p['peak'])})", f"max {p['max_alt']:.0f} deg",
          f"az {p['peak_az']:.0f} deg", f"sun {p['sun_alt']:.0f} deg")
    # Line 2: the visible window and its length
    print(f"  visible {to_zulu(start)} to {to_zulu(end)} ({lit_seconds:.0f} s)")
    # Line 3: where the ISS is in the sky at each end of the window
    print(f"  {start_label}: alt {alt_s.degrees:.0f} deg, az {az_s.degrees:.0f} deg | "
          f"{end_label}: alt {alt_e.degrees:.0f} deg, az {az_e.degrees:.0f} deg")
    # Line 4: the same window in local time
    print(f"  Local: {to_local(start)} to {to_local(end)}")

def plot_sky_path(p):
    # 200 evenly spaced times from rise to set, for a smooth path
    t_arr = ts.linspace(p["rise"], p["set"], 200)

    # Altitude and azimuth of the ISS at each time, as seen from Toronto
    alt, az, _ = (iss - site).at(t_arr).altaz()

    # Azimuth in radians (matplotlib's polar axes use radians for the angle)
    theta = np.radians(az.degrees)
    # Radius = 90 - altitude, so the center of the plot is straight overhead
    r = 90 - alt.degrees

    # True wherever the ISS is in sunlight, False where it is in Earth's shadow
    lit = iss.at(t_arr).is_sunlit(eph)

    fig = plt.figure()  # create the figure
    ax = fig.add_subplot(projection="polar")  # polar axes for the sky dome
    ax.set_theta_zero_location("N")  # put north at the top
    ax.set_theta_direction(1)        # counterclockwise: east on the left, like looking up (matches Heavens-Above)

    # Keep r only where the ISS is in shadow (NaN elsewhere, so nothing is drawn there)
    ax.plot(theta, np.where(lit, np.nan, r), "--", color="gray", label="in shadow (not visible)")
    # Keep r only where the ISS is sunlit
    ax.plot(theta, np.where(lit, r, np.nan), "-", color="tab:blue", label="sunlit (visible)")

    ax.plot(theta[0], r[0], "go", label="rise")    # green dot where the pass starts
    ax.plot(theta[-1], r[-1], "ro", label="set")   # red dot where the pass ends
    i_peak = np.argmax(alt.degrees)                # index of the highest point
    ax.plot(theta[i_peak], r[i_peak], "b^", label="peak")  # blue triangle at the peak

    # First sunlit sample = the moment the ISS exits Earth's shadow
    lit_idx = np.where(lit)[0]
     # Only mark a shadow exit if the ISS was in shadow at the start of the pass (index 0)
    if len(lit_idx) > 0 and lit_idx[0] > 0:
        ax.plot(theta[lit_idx[0]], r[lit_idx[0]], "*", color="gold", markersize=12, label="exits shadow")

     # Last sunlit sample: if it isn't the final sample, the ISS enters Earth's shadow before it sets
    if len(lit_idx) > 0 and lit_idx[-1] < len(t_arr) - 1:
        ax.plot(theta[lit_idx[-1]], r[lit_idx[-1]], "v", color="darkorange", markersize=10, label="enters shadow")

    ax.set_ylim(0, 90)                                # outer edge is the horizon
    ax.set_yticks([0, 30, 60, 90])                    # rings at these radii
    ax.set_yticklabels(["90°", "60°", "30°", "0°"])   # label rings by elevation
    ax.set_rlabel_position(135)                       # move elevation labels off the compass labels

    ax.set_xticks(np.radians([0, 90, 180, 270]))      # ticks at the four compass points only
    ax.set_xticklabels(["N", "E", "S", "W"])          # compass letters instead of degrees

    # Put the legend outside the circle on the right, with a smaller font so it isn't clipped
    ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.0), fontsize=8)
    # Shrink the plot area to leave room for the legend on the right
    plt.subplots_adjust(right=0.7)
     # Two-line title: city and pass, then the peak time in Zulu and local (offset spelled out)
    ax.set_title(f"ISS pass over {SITE_NAME}\n\n{to_zulu(p['peak'])}  |  Local: {to_local(p['peak'])}\n", fontsize=10)
    plt.show()  # open the plot window

def break_wrap(lon, lat, center=0.0):
    # Re-express longitudes in the range [center-180, center+180], so the map edge falls
    # on the far side of the world from the site instead of on the dateline
    lon = (np.asarray(lon) - center + 180) % 360 - 180 + center
    # Where the line jumps from one map edge to the other, insert NaN so it isn't drawn across the map
    jumps = np.where(np.abs(np.diff(lon)) > 180)[0] + 1
    return np.insert(lon, jumps, np.nan), np.insert(lat, jumps, np.nan)


def plot_ground_track(p):
    # Half an orbit in days (period_min is in minutes, 1440 minutes per day)
    half = period_min / 2 / 1440

    # 1000 times covering one full orbit, centered on the peak of the pass
    t_orbit = ts.linspace(p["peak"] - half, p["peak"] + half, 1000)
    # 200 times covering just the pass itself, rise to set
    t_pass = ts.linspace(p["rise"], p["set"], 200)

    # Point on Earth's surface directly below the ISS at each time
    sub_orbit = wgs84.subpoint_of(iss.at(t_orbit))
    sub_pass = wgs84.subpoint_of(iss.at(t_pass))
    sub_peak = wgs84.subpoint_of(iss.at(p["peak"]))  # single position at the peak

    # CHANGED: wrap longitudes around the site's longitude instead of around 0
    lon_o, lat_o = break_wrap(sub_orbit.longitude.degrees, sub_orbit.latitude.degrees, SITE_LON)
    lon_p, lat_p = break_wrap(sub_pass.longitude.degrees, sub_pass.latitude.degrees, SITE_LON)

    # Numerical checks, printed in the terminal
    incl = np.degrees(iss.model.inclo)  # inclination from the TLE, in degrees
    print(f"Inclination from TLE: {incl:.2f} deg, max latitude on track: {np.nanmax(lat_o):.2f} deg")
    gap = (lon_o[0] - lon_o[-1]) % 360          # start minus end longitude of the plotted orbit
    predicted = 360 * period_min / 1436.07      # Earth's rotation during one orbit
    print(f"Track gap: {gap:.1f} deg, predicted from Earth's rotation: {predicted:.1f} deg")

    # CHANGED: map projection centered on the site's longitude
    proj = ccrs.PlateCarree(central_longitude=SITE_LON)
    fig = plt.figure(figsize=(11, 5.5))   # wide figure for a world map
    ax = plt.axes(projection=proj)        # CHANGED: use the centered projection

    # CHANGED: zoom or show the whole world. Extents are relative to the center, so no dateline problem
    ZOOM = True                  # set to False to show the whole world
    ZOOM_LON, ZOOM_LAT = 50, 30  # half-widths of the zoom window, in degrees
    if ZOOM:
        ax.set_extent([-ZOOM_LON, ZOOM_LON,
                       max(SITE_LAT - ZOOM_LAT, -90), min(SITE_LAT + ZOOM_LAT, 90)],
                      crs=proj)
    else:
        ax.set_global()  # whole world, centered on the site

    ax.coastlines(linewidth=0.6)                    # draw coastlines
    ax.add_feature(cfeature.BORDERS, linewidth=0.3) # draw country borders
    ax.gridlines(draw_labels=True, linewidth=0.3)   # lat/lon grid with labels

    # Shade the part of Earth that is in darkness at the moment of the peak
    ax.add_feature(Nightshade(p["peak"].utc_datetime(), alpha=0.25))

    # Our coordinates are plain lon/lat degrees, so tell cartopy that with transform
    crs = ccrs.PlateCarree()
    ax.plot(lon_o, lat_o, ".", markersize=2, color="gray", transform=crs, label="one full orbit")
    ax.plot(lon_p, lat_p, "-", linewidth=3, color="tab:blue", transform=crs, label="during the pass")
    ax.plot(sub_peak.longitude.degrees, sub_peak.latitude.degrees, "b^", transform=crs, label="ISS at peak")
    ax.plot(site.longitude.degrees, site.latitude.degrees, "r*", markersize=14, transform=crs, label=SITE_NAME)

    ax.legend(loc="lower left", fontsize=8)  # legend in the corner
    # Two-line title: city on the first line, Zulu and local peak time on the second
        # Two-line title: city and pass, then the peak time in Zulu and local (offset spelled out)
    ax.set_title(f"ISS ground track around the pass ({SITE_NAME})\n\n{to_zulu(p['peak'])}  |  Local: {to_local(p['peak'])}\n", fontsize=10)

    plt.show()  # open the plot window

# Plot the first visible pass, if there is one
# Pick which pass to plot: the first visible one, or else the first geometric pass (for testing)
if visible:
    target = visible[0]
elif passes:
    target = passes[0]
    print("No visible passes found, so plotting the first geometric pass instead.")
else:
    target = None  # nothing to plot

if target is not None:
    plot_sky_path(target)      # sky chart: close this window to see the next
    plot_ground_track(target)  # ground track