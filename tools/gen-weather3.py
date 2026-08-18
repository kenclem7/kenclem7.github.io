#!/usr/bin/env python3
"""weather3/index.html is a BYTE-COPY of weather10/index.html (DESIGN.md section 4).

  py tools/gen-weather3.py            copy weather10/index.html -> weather3/index.html
  py tools/gen-weather3.py --check    exit 1 if the two differ (CI tripwire, no write)

Since 2026-08-18 the two forecast pages are one source file that branches on
location.pathname at boot: IS3 sets HOURS 72 vs 240, DAYSN = HOURS/24 drives the api
forecast_days and the "N Day Weather Forecast" title, and boot JS turns the current
page's nav link into the inert .here chip. "Generating" weather3 is copying the file.
The old needle-replace generator - and its whole silent-no-op failure class - is gone;
its final form lives in the git history of this file.

Comparison and output are LF-normalized: with core.autocrlf the working tree holds CRLF
while the committed bytes are LF (the line-ending trap, DESIGN.md section 4)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "weather10", "index.html")
DST = os.path.join(ROOT, "weather3", "index.html")


def read_lf(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def main():
    src = read_lf(SRC)
    assert 'location.pathname.indexOf("/weather3")' in src, (
        "weather10/index.html no longer carries the IS3 pathname branch - a plain copy "
        "would ship a broken 3 Day page; restore the branch or rethink section 4"
    )
    if "--check" in sys.argv:
        if read_lf(DST) != src:
            sys.stderr.write(
                "weather3/index.html differs from weather10/index.html: it is a byte-copy - "
                "run  py tools/gen-weather3.py  and commit both together (never hand-edit weather3)\n"
            )
            sys.exit(1)
        print("weather3/index.html is a faithful copy of weather10/index.html")
        return
    with open(DST, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print("copied weather10/index.html -> weather3/index.html (%d chars)" % len(src))


if __name__ == "__main__":
    main()
