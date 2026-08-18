#!/usr/bin/env python3
"""Regenerate weather3/index.html from weather10/index.html (DESIGN.md section 4).

  py tools/gen-weather3.py            regenerate weather3/index.html
  py tools/gen-weather3.py --check    exit 1 if weather3 is stale (CI tripwire, no write)

Every needle count is asserted BEFORE any replace runs, so a weather10 edit that breaks
a needle fails loudly here instead of silently shipping a stale or half-generated 3 Day
page. The riskiest needle is the pagenav swap: a ~150-char exact-HTML substring that a
whitespace or attribute change would quietly stop matching (str.replace does not error).

Comparison and output normalize CRLF to LF: with core.autocrlf the working tree holds
CRLF while the committed bytes are LF either way (the line-ending trap, DESIGN.md
section 4), so byte comparisons must happen in LF space to mean anything.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "weather10", "index.html")
DST = os.path.join(ROOT, "weather3", "index.html")

PAGENAV10 = ('<a href="/weather3/">3 Day<span class="fc"> Forecast</span></a>'
             '<span class="here">10 Day<span class="fc"> Forecast</span></span>')
PAGENAV3 = ('<span class="here">3 Day<span class="fc"> Forecast</span></span>'
            '<a href="/weather10/">10 Day<span class="fc"> Forecast</span></a>')

REPLACES = [  # (needle in weather10, replacement, exact count required in weather10)
    ("HOURS = 240", "HOURS = 72", 1),
    ("forecast_days: 10", "forecast_days: 3", 2),
    ("10 Day Weather Forecast", "3 Day Weather Forecast", 2),
    (PAGENAV10, PAGENAV3, 1),
]


def read_lf(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def generate():
    s = read_lf(SRC)
    for old, _new, n in REPLACES:
        found = s.count(old)
        assert found == n, (
            "needle %r: expected %d occurrence(s) in weather10, found %d - "
            "fix weather10/index.html or update this script AND DESIGN.md section 4"
            % (old[:60], n, found)
        )
    for old, new, _n in REPLACES:
        s = s.replace(old, new)
    return s


def main():
    out = generate()
    if "--check" in sys.argv:
        if read_lf(DST) != out:
            sys.stderr.write(
                "weather3/index.html is stale: run  py tools/gen-weather3.py  and commit it "
                "alongside the weather10 change\n"
            )
            sys.exit(1)
        print("weather3/index.html is in sync with weather10/index.html")
        return
    with open(DST, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print("wrote weather3/index.html (%d chars)" % len(out))


if __name__ == "__main__":
    main()
