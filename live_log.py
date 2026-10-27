# live_log.py - print the ISS position from stations.tle once per second for 30 seconds
import os                                   # to check that the TLE file exists
import time                                 # for the one-second pause between lines
from skyfield.api import load, wgs84        # satellite loader and Earth-surface model

print("live_log.py started", flush=True)    # proves the script is actually running

# Stop with a clear message if the TLE file isn't in the folder the terminal is in
if not os.path.exists("stations.tle"):
    raise SystemExit("stations.tle not found in this folder: " + os.getcwd())

ts = load.timescale()                                            # timescale for creating times
sats = {s.name: s for s in load.tle_file("stations.tle")}        # satellites stored in the file
print("satellites in file:", len(sats), flush=True)              # a real download has about 16
iss = sats["ISS (ZARYA)"]                                        # pick the ISS

for _ in range(30):                                              # 30 lines, one per second
    t = ts.now()                                                 # current time from your PC clock
    sub = wgs84.subpoint_of(iss.at(t))                           # point on Earth directly below the ISS
    print(t.utc_strftime("%H:%M:%S"),                            # UTC time to compare with n2yo
          f"lat {sub.latitude.degrees:6.2f}  lon {sub.longitude.degrees:7.2f}",
          flush=True)                                            # show each line immediately
    time.sleep(1)                                                # wait one second before the next line