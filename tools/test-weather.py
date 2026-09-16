#!/usr/bin/env python3
"""Tests for the forecast pages.

  py tools/test-weather.py            offline only - no network, what CI runs
  py tools/test-weather.py --live     adds checks that call Open-Meteo

The offline half pulls the real JavaScript out of weather10/index.html and runs it in node,
rather than restating the logic here. A test that carries its own copy of the rules stops
testing the page the moment someone edits the page, which is exactly when it matters; this
way, changing ladder() in the HTML is what the assertions see.

WHY THE --live HALF EXISTS, and why it is worth running by hand now and then. Whether a
non-CONUS location gets a forecast at all rests on the page recognising Open-Meteo's way of
saying "off this model's grid", and that answer is Open-Meteo's to change without telling
anyone. It already has: this file used to pin the reason string of an HTTP 400, and on
2026-09-16 out-of-coverage became an HTTP 200 whose body carries bare nan coordinates, which
is not even valid JSON. The old check would have caught it - the status assertion, not the
string one - but nothing runs it on a schedule, so what actually caught it was Bordeaux
showing an error banner.

So the live half now asks the behavioural question rather than pinning a string: it sends a
real out-of-coverage request and feeds whatever comes back through the page's own
backboneFallback(), asserting only that the page calls it "coverage". That survives Open-Meteo
rewording anything, and fails exactly when the page would fail. It stays out of CI so a bad
minute at Open-Meteo cannot redden an unrelated commit, which also means nobody is watching it
automatically: run it after any Open-Meteo-facing change.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "weather10", "index.html")

failures = []
checks = [0]


def check(name, ok, detail=""):
    checks[0] += 1
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, ("  <- " + detail) if detail else ""))
        failures.append(name)


def extract(src, name):
    """Cut one top-level `function name(...) { ... }` out of the page by brace matching."""
    start = src.index("function %s(" % name)
    depth, i = 0, src.index("{", start)
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


def node(script):
    # The page's JavaScript is the thing under test, so node is a hard requirement rather than a
    # nicety. GitHub's ubuntu-latest ships it; say so plainly if some other runner does not.
    try:
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("node is not on PATH - this suite runs the page's own JavaScript and needs it")
    if r.returncode != 0:
        sys.exit("node failed:\n" + r.stderr)
    return json.loads(r.stdout)


def offline():
    src = open(PAGE, encoding="utf-8").read()

    # ---------------------------------------------------------------- axis ladders
    # grid() is the page's own gridline loop; running the real one is the only honest way to
    # assert that the top line actually draws, since that depends on its <= hi + 1e-9 tolerance.
    helpers = extract(src, "niceTop") + "\n" + extract(src, "ladder")
    harness = helpers + r"""
    function lines(lo, hi, step) { var o = []; for (var v = lo; v <= hi + 1e-9; v += step) o.push(v); return o; }
    var PRECIP = [[0.1,0.25,0.5,1,2,3,5,10],[0.02,0.05,0.1,0.25,0.5,0.5,1,2.5]];
    var VIS    = [[2.5,5,10],[0.5,1,2.5]];
    var AQI    = [[50,100,150,200],[25,25,50,50]];
    var out = { precip: [], vis: [], aqi: [] };
    function run(key, rungs, steps, maxes, cap) {
      maxes.forEach(function (m) {
        var mm = cap === null ? m : Math.min(m, cap);
        var r = (key === "precip" && mm > 10) ? [niceTop(mm), niceTop(mm) / 4] : ladder(mm, rungs, steps);
        var top = r[0], step = r[1], g = lines(0, top, step);
        var dec = key === "precip" ? (Math.round(step * 100) % 10 === 0 ? 1 : 2) : null;
        out[key].push({ max: m, capped: mm, top: top, step: step, n: g.length,
          last: g[g.length - 1],
          labels: dec === null ? g.map(function (v) { return String(v); })
                               : g.map(function (v) { return v.toFixed(dec); }) });
      });
    }
    run("precip", PRECIP[0], PRECIP[1], [0,0.004,0.09,0.1,0.101,0.17,0.25,0.26,0.3,0.5,0.51,0.9,1,1.01,1.6,2,2.076,2.9,3,3.1,4.2,5,5.1,9.9,10,10.5,14.3,47], null);
    run("vis",    VIS[0],    VIS[1],    [0,0.4,1,2.4,2.5,2.6,4.9,5,5.1,6,9.9,10,30,67.3], 10);
    run("aqi",    AQI[0],    AQI[1],    [0,12,48,50,51,63,80,100,101,120,150,151,175,200,260,999], 200);
    console.log(JSON.stringify(out));
    """
    ax = node(harness)

    for key, rungs, cap in (("precip", [0.1, 0.25, 0.5, 1, 2, 3, 5, 10], None),
                            ("vis", [2.5, 5, 10], 10),
                            ("aqi", [50, 100, 150, 200], 200)):
        bad_top = [r for r in ax[key] if r["top"] < r["capped"] - 1e-9]
        check("%s: axis top is never below the data" % key, not bad_top, str(bad_top[:2]))

        # the lowest rung that fits - a higher one would waste the row, which is the whole point
        def lowest(m):
            for r in rungs:
                if m <= r + 1e-9:
                    return r
            return None
        wrong = [r for r in ax[key]
                 if lowest(r["capped"]) is not None and abs(r["top"] - lowest(r["capped"])) > 1e-9]
        check("%s: picks the LOWEST rung that fits" % key, not wrong, str(wrong[:2]))

        missing = [r for r in ax[key] if abs(r["last"] - r["top"]) > 1e-9]
        check("%s: top gridline actually draws" % key, not missing, str(missing[:2]))

        check("%s: axis top is never zero (no divide by zero)" % key,
              all(r["top"] > 0 for r in ax[key]))

        sane = [r for r in ax[key] if not (3 <= r["n"] <= 9)]
        check("%s: gridline count stays legible (3-9)" % key, not sane, str(sane[:2]))

    # the 0.25 -> "0.3" bug, nailed shut: every label must read back as its exact gridline value
    lied = []
    for r in ax["precip"]:
        for i, lab in enumerate(r["labels"]):
            if abs(float(lab) - i * r["step"]) > 1e-9:
                lied.append((r["top"], lab))
    check("precip: every label equals its gridline value", not lied, str(lied[:3]))

    # The caps are load-bearing twice over: they bound the drawn line AND they bound the max that
    # feeds the ladder, so losing one would ladder the axis to a nonsense top. The sweep above
    # applies the caps itself, which means it would happily pass on a page that had lost them -
    # so run the page's OWN scan loops here instead of restating them. (Found the hard way: a
    # mutation removing Math.min(data.vis[i], 10) was caught only by the weather3 copy tripwire.)

    vis_block = re.search(r"(var vmax = 0, hasVis = false;[\s\S]*?\n  \})", src)
    aqi_block = re.search(r"(var qmax = 0, hasAqi = false;[\s\S]*?\n    \})", src)
    check("visibility max-scan found in the page", vis_block is not None)
    check("aqi max-scan found in the page", aqi_block is not None)
    if vis_block and aqi_block:
        r = node(
            "var HOURS=4, i;"
            "var data={vis:[2.0,67.3,9.0,null], aqi:[40,260,55,null]};"
            + vis_block.group(1) + "\n" + aqi_block.group(1) + "\n"
            "console.log(JSON.stringify({vmax:vmax, hasVis:hasVis, qmax:qmax, hasAqi:hasAqi}));")
        check("page's own scan caps 67.3 mi at 10", r["vmax"] == 10,
              "vmax=%s - the Math.min(data.vis[i], 10) cap is gone" % r["vmax"])
        check("page's own scan pins AQI 260 at 200", r["qmax"] == 200,
              "qmax=%s - the Math.min(data.aqi[i], 200) pin is gone" % r["qmax"])
        check("page's own scan sets hasVis/hasAqi", r["hasVis"] and r["hasAqi"])
        # and the capped max must still land on the top rung
        check("capped 67.3 mi lands on the 10 mi rung",
              [x for x in ax["vis"] if x["max"] == 67.3][0]["top"] == 10)
        check("capped AQI 260/999 land on the 200 rung",
              all(x["top"] == 200 for x in ax["aqi"] if x["max"] in (260, 999)))

    # ---------------------------------------------------------------- fallback predicate
    # Every one of these is a real response shape observed from Open-Meteo: the 400s and the 429s
    # on 2026-08-22, the two HTTP 200 bodies on 2026-09-16. Only the shapes that mean "off NBM's
    # grid" may come back "coverage", and only a body NBM could not serve may come back
    # "unavailable"; everything else must come back "" and stay an error in front of the reader,
    # because a request we broke ourselves quietly serving the 25 km inland forecast is the bug
    # the move to NBM exists to fix.
    NAN_BODY = ('{"latitude":nan,"longitude":nan,"generationtime_ms":0.0029,'
                '"utc_offset_seconds":7200,"timezone":"Europe/Paris","timezone_abbreviation":"GMT+2"}')
    STALL_BODY = "Unexpected error while streaming data: timeoutReached"
    fallback_fn = extract(src, "backboneFallback")
    # status, reason, body, want, label
    cases = [
        (400, "No data is available for this location", "", "coverage", "out of coverage (400)"),
        (200, "", NAN_BODY, "coverage", "out of coverage (nan coords)"),
        (200, "", STALL_BODY, "unavailable", "upstream stall"),
        (400, "Data corrupted at path ''. Cannot initialize MultiDomains from invalid String value ncep_nbm_typo.", "", "", "typo'd model"),
        (400, "Data corrupted at path ''. Cannot initialize SurfacePressure... from invalid String value banana_2m.", "", "", "bad variable"),
        (400, "Parameter 'latitude' and 'longitude' must have the same number of elements", "", "", "missing latitude"),
        (400, "Latitude must be in range of -90 to 90°. Given: 999.0.", "", "", "lat out of range"),
        (400, "Forecast days is invalid. Allowed range 0 to 16. Given 16.", "", "", "forecast_days"),
        (429, "Too many concurrent requests", "", "", "rate limit (concurrent)"),
        (429, "Minutely API request limit exceeded. Please try again in one minute.", "", "", "rate limit (minutely)"),
        (500, "", "", "", "upstream 5xx"),
        (0,   "", "", "", "network reject (no status)"),
        # A 200 whose body is valid JSON never reaches here at all: api() only throws on a body it
        # could not parse, so a 200 with an empty body means the fetch layer gave us nothing.
        (200, "", "", "", "200 with an empty body"),
        # A nan buried in the data rather than the coordinates is a glitch somewhere NBM does
        # cover. It still cannot be parsed, so ECMWF still answers - but as "unavailable", which
        # is the honest label, and not as "outside NBM coverage", which would be a lie about
        # San Diego.
        (200, "", '{"latitude":32.7,"longitude":-117.1,"hourly":{"temperature_2m":[nan,71.2]}}',
         "unavailable", "nan in the data, not the coords"),
    ]
    js = (fallback_fn + ";var C=" + json.dumps([[c[0], c[1], c[2]] for c in cases]) + ";"
          "console.log(JSON.stringify(C.map(function(c){"
          "return backboneFallback({status:c[0],reason:c[1],body:c[2]});})));")
    for (status, reason, body, want, label), why in zip(cases, node(js)):
        check("fallback %-32s -> %s" % (label, want or "rethrow"),
              why == want, "got %r for status=%s reason=%r" % (why, status, reason[:40]))
    check("fallback %-32s -> rethrow" % "no error object at all",
          node(fallback_fn + ";console.log(JSON.stringify("
               "[backboneFallback(null), backboneFallback(undefined)]))") == ["", ""])

    # A 200 that parses but has no usable hourly block is out of coverage too - what we would get
    # if Open-Meteo ever writes those unplaceable coordinates as a valid JSON null. The backbone
    # owns the time axis, so "parsed fine" is not the same question as "can be built on".
    usable_fn = extract(src, "usableBackbone")
    payloads = [
        ('{"latitude":null,"longitude":null,"timezone":"Europe/Paris"}', False, "no hourly at all"),
        ('{"hourly":{"time":[]}}', False, "hourly present but empty"),
        ('{"hourly":{"temperature_2m":[70]}}', False, "hourly with no time axis"),
        ('{"hourly":{"time":["2026-09-16T00:00"],"temperature_2m":[70]}}', True, "a real answer"),
    ]
    got = node(usable_fn + ";var P=" + json.dumps([p[0] for p in payloads]) + ";"
               "console.log(JSON.stringify(P.map(function(s){"
               "return usableBackbone(JSON.parse(s));})));")
    for (payload, want, label), ok in zip(payloads, got):
        check("usableBackbone %-26s -> %s" % (label, "keep" if want else "fall back"),
              ok == want, payload[:60])

    # ---------------------------------------------------------------- serve.py port precedence
    env = dict(os.environ, PORT="9999")
    r = subprocess.run([sys.executable, "-c",
        "import os,sys;sys.argv=['serve.py','8080'];"
        "sys.path.insert(0,%r);"
        "import serve;"
        "print(sys.argv[1] if len(sys.argv)>1 else os.environ.get('PORT') or '3463')" % os.path.join(ROOT, "tools")],
        capture_output=True, text=True, env=env)
    check("serve.py: explicit argument beats $PORT", r.stdout.strip() == "8080", r.stdout.strip())
    body = open(os.path.join(ROOT, "tools", "serve.py"), encoding="utf-8").read()
    check("serve.py: precedence not silently reordered",
          'sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT")' in body)

    # ---------------------------------------------------------------- page invariants
    check("weather3 is a faithful copy of weather10",
          subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen-weather3.py"), "--check"],
                         capture_output=True).returncode == 0)
    # The probe goes to a real temp dir, not into tools/: an early failure would otherwise strand
    # a .syntax-probe.js in the repo, which is untracked noise the .gitignore does not cover.
    script = re.search(r"<script(?![^>]*src=)[^>]*>([\s\S]*?)</script>", src).group(1)
    with tempfile.TemporaryDirectory() as tmp:
        probe = os.path.join(tmp, "probe.js")
        with open(probe, "w", encoding="utf-8") as f:
            f.write(script)
        ok = subprocess.run(["node", "--check", probe], capture_output=True).returncode == 0
    check("inline script parses", ok)
    check("backbone asks NBM first", 'models: "ncep_nbm_conus"' in src)
    check("ECMWF is still the fallback", 'models: "ecmwf_ifs025"' in src)
    check("footer names the model that answered", 'id="footmodel"' in src)
    # Falling back for the two reasons must not read the same in the footer: "outside NBM
    # coverage" is permanent and expected for that spot, "NBM unavailable" is Open-Meteo having a
    # bad minute and worth a second look. One label for both would hide the difference.
    fm = re.search(r"var FOOTMODEL = \{[\s\S]*?\};", src)
    check("FOOTMODEL still found in the page", fm is not None)
    if fm:
        labels = node(fm.group(0) + ";console.log(JSON.stringify("
                      '[FOOTMODEL[""], FOOTMODEL.coverage, FOOTMODEL.unavailable]))')
        check("footer: NBM answered", labels[0] == "NOAA NBM model", labels[0])
        check("footer: out of coverage names ECMWF and why",
              "ECMWF" in labels[1] and "coverage" in labels[1], labels[1])
        check("footer: NBM unavailable names ECMWF and why",
              "ECMWF" in labels[2] and "unavailable" in labels[2], labels[2])
        check("footer: the two fallbacks do not read the same", labels[1] != labels[2])


def live():
    def get(url):
        """-> (status, parsed-or-None, raw body). Open-Meteo answers with HTTP 200 and bodies that
        are not JSON at all - bare nan coordinates, plain-text upstream errors - so the raw text
        has to survive the helper: it is what the page's own backboneFallback() reads."""
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                status, body = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read().decode("utf-8", "replace")
        try:
            return status, json.loads(body), body
        except ValueError:
            return status, None, body

    base = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&timezone=auto"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
            "&forecast_days=10&models=%s&hourly=temperature_2m,apparent_temperature,precipitation,"
            "weather_code,cloud_cover,wind_speed_10m,wind_gusts_10m,wind_direction_10m")

    # The page's own classifier, run against what Open-Meteo actually says right now. Restating
    # the rules here would stop testing the page the moment someone edited the page.
    page = open(PAGE, encoding="utf-8").read()
    fallback_fn = extract(page, "backboneFallback")

    def classify(status, reason, body):
        return node(fallback_fn + ";console.log(JSON.stringify(backboneFallback(%s)))"
                    % json.dumps({"status": status, "reason": reason, "body": body}))

    status, j, body = get(base % (32.72, -117.16, "ncep_nbm_conus"))
    check("live: NBM answers 200 in CONUS", status == 200, str(status))
    check("live: NBM's CONUS answer is JSON", j is not None, body[:120])
    if status == 200 and j:
        h = j.get("hourly", {})
        check("live: NBM carries all 8 backbone variables",
              all(k in h for k in ["temperature_2m", "apparent_temperature", "precipitation",
                                   "weather_code", "cloud_cover", "wind_speed_10m",
                                   "wind_gusts_10m", "wind_direction_10m"]))
        check("live: NBM covers the 240 hours weather10 needs",
              all(len([v for v in h[k] if v is not None]) >= 240 for k in h if k != "time"),
              "shortest series %d h" % min(len([v for v in h[k] if v is not None])
                                           for k in h if k != "time"))
    elif status == 200:
        # Seen on 2026-09-16: apparent_temperature stalled upstream and Open-Meteo gave up after
        # ~32s with a plain-text body. The page now falls back and says so in the footer, which is
        # what the next check confirms, so this is a bad minute at Open-Meteo and not a regression.
        check("live: a non-JSON CONUS answer falls back as unavailable",
              classify(200, "", body) == "unavailable", body[:120])

    # THE important one - see the module docstring. Not "Open-Meteo still words it this way" but
    # "the page still recognises whatever Open-Meteo says", which is the thing that can break.
    status, j, body = get(base % (51.51, -0.13, "ncep_nbm_conus"))
    reason = (j or {}).get("reason", "")
    check("live: the page reads London as outside NBM coverage",
          classify(status, reason, body) == "coverage",
          "Open-Meteo now answers HTTP %s reason=%r body=%r - backboneFallback() must learn this "
          "shape or every non-CONUS location breaks" % (status, reason, body[:120]))

    status, _, _ = get(base % (51.51, -0.13, "ecmwf_ifs025"))
    check("live: ECMWF still answers where NBM does not", status == 200, str(status))


if __name__ == "__main__":
    print("offline")
    offline()
    if "--live" in sys.argv:
        print("live (Open-Meteo)")
        live()
    print("\n%d checks, %d failed" % (checks[0], len(failures)))
    for f in failures:
        print("  FAILED: %s" % f)
    sys.exit(1 if failures else 0)
