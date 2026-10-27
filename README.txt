# ISS Pass Predictor

One-sentence description of what it does.

## What it does
- Finds upcoming ISS passes over a location
- Filters for passes that are actually visible (sunlit ISS, dark sky)
- Plots the sky path and ground track
- Passes over 10 days (for now)

## How to run it
pip install skyfield matplotlib numpy
python passes.py

## Validation
Table comparing my results to Heavens-Above for 3 passes, plus
the physics checks (orbital period, inclination, ground track shift).

## Limitations
TLE accuracy degrades with age; visibility checked at the peak only <-- max TLE age is 2 days (research why should I not make it longer/shorter) then it refreshes
for the pass filter; etc. 