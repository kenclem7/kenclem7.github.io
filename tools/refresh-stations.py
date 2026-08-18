#!/usr/bin/env python3
"""Refresh data/tide-stations.json and data/current-stations.json from NOAA CO-OPS
metadata (DESIGN.md section 5). Stdlib only.

  py tools/refresh-stations.py

Keeps exactly the fields the pages consume, POSITIONALLY - the row shape is load-bearing
(nearestStations indexes into it by column number):

  tide-stations.json:    [id, name, lat, lng]
  current-stations.json: [id, currbin, name, lat, lng]

After running: eyeball the diff, bump STATIONS_V in weather10/index.html (the pages cache
these files in localStorage behind that version pin), regenerate weather3, commit all of it
together. Cadence rides the January checklist in DESIGN.md section 6.
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type="


def fetch(kind):
    with urllib.request.urlopen(MDAPI + kind, timeout=120) as r:
        stations = json.load(r)["stations"]
    assert len(stations) > 1000, "suspiciously few %s stations (%d) - NOAA schema change?" % (kind, len(stations))
    return stations


def rnd(v):
    return round(float(v), 3)


def write(name, rows):
    path = os.path.join(ROOT, "data", name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(rows, f, separators=(",", ":"), ensure_ascii=False)
    print("wrote %s: %d stations, %d bytes" % (name, len(rows), os.path.getsize(path)))


tide = [[s["id"], s["name"], rnd(s["lat"]), rnd(s["lng"])]
        for s in fetch("tidepredictions")]
cur = [[s["id"], s["currbin"], s["name"], rnd(s["lat"]), rnd(s["lng"])]
       for s in fetch("currentpredictions")]

for row in tide:
    assert isinstance(row[1], str) and -90 <= row[2] <= 90 and -180 <= row[3] <= 180, row
for row in cur:
    assert isinstance(row[2], str) and -90 <= row[3] <= 90 and -180 <= row[4] <= 180, row

write("tide-stations.json", tide)
write("current-stations.json", cur)
print("now: bump STATIONS_V in weather10/index.html, run tools/gen-weather3.py, commit together")
