# check_tle.py - print the TLE age and where the saved file says the ISS is right now
from skyfield.api import load, wgs84

ts = load.timescale()                                        # timescale for creating times
sats = {s.name: s for s in load.tle_file("stations.tle")}    # satellites stored in the file
iss = sats["ISS (ZARYA)"]                                    # pick the ISS
now = ts.now()                                               # current time from your PC clock
sub = wgs84.subpoint_of(iss.at(now))                         # point on Earth directly below the ISS

print("satellites in file:", len(sats))                      # 1 means this is the fallback copy
print("TLE epoch:", iss.epoch.utc_iso(), "| age (days):", round(now - iss.epoch, 2))
print("now (UTC):", now.utc_iso())
print(f"ISS now: lat {sub.latitude.degrees:.2f}, lon {sub.longitude.degrees:.2f}")