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


def cut(text, pattern, what):
    """Cut a regex match out of a page, or stop the suite saying what it could not find."""
    m = re.search(pattern, text)
    if not m:
        sys.exit("could not find %s in the page - the checks below read it from there" % what)
    return m.group(0)


def units_block(text):
    """The page's whole units block - converters, both tables, and the bw_units read that picks
    one - from `function keep` through `var U = ...`. Cut as a block rather than line by line, so
    a mutation of any line inside it is run, not merely missed by a regex."""
    return cut(text, r"function keep\(v\)[\s\S]*?var U = metric \? UNITS_METRIC : UNITS_IMPERIAL;", "the units block")


def unit_tables(text):
    """The units block, runnable in node: fmtIn beside it, and load() stubbed to an empty store."""
    return ("var load = function () { return null; };\n" + extract(text, "fmtIn") + "\n"
            + units_block(text) + "\n")


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

    # The Imperial | Metric tables, cut out of the page and run as they are. The page fetches in
    # imperial and converts only where it shows a value, so these two tables are the whole of the
    # unit logic - and the precip ladder lives in them, so the ladder checks run over both.
    units = unit_tables(src)

    # ---------------------------------------------------------------- axis ladders
    # grid() is the page's own gridline loop; running the real one is the only honest way to
    # assert that the top line actually draws, since that depends on its <= hi + 1e-9 tolerance.
    helpers = extract(src, "niceTop") + "\n" + extract(src, "ladder") + "\n" + units
    harness = helpers + r"""
    function lines(lo, hi, step) { var o = []; for (var v = lo; v <= hi + 1e-9; v += step) o.push(v); return o; }
    var VIS    = [[2.5,5,10],[0.5,1,2.5]];
    var AQI    = [[50,100,150,200],[25,25,50,50]];
    var out = { rungs: { "precip": UNITS_IMPERIAL.pRungs, "precip (metric)": UNITS_METRIC.pRungs } };
    /* u is the unit table of a precip run: past its top rung the page hands over to niceTop, and
       its labels print at u.pDec - both exactly as render() does it */
    function run(key, rungs, steps, maxes, cap, u) {
      out[key] = [];
      maxes.forEach(function (m) {
        var mm = cap === null ? m : Math.min(m, cap);
        var r = (u && mm > rungs[rungs.length - 1]) ? [niceTop(mm), niceTop(mm) / 4] : ladder(mm, rungs, steps);
        var top = r[0], step = r[1], g = lines(0, top, step), dec = u ? u.pDec(step) : null;
        out[key].push({ max: m, capped: mm, top: top, step: step, n: g.length,
          last: g[g.length - 1],
          labels: dec === null ? g.map(function (v) { return String(v); })
                               : g.map(function (v) { return v.toFixed(dec); }) });
      });
    }
    run("precip", UNITS_IMPERIAL.pRungs, UNITS_IMPERIAL.pSteps,
        [0,0.004,0.09,0.1,0.101,0.17,0.25,0.26,0.3,0.5,0.51,0.9,1,1.01,1.6,2,2.076,2.9,3,3.1,4.2,5,5.1,9.9,10,10.5,14.3,47], null, UNITS_IMPERIAL);
    run("precip (metric)", UNITS_METRIC.pRungs, UNITS_METRIC.pSteps,
        [0,0.1,2.3,2.5,2.6,4.9,5,5.1,9.9,10,10.1,24,25,26,49,50,52.8,74,75,76,124,125,126,249,250,251,363,1194], null, UNITS_METRIC);
    run("vis",    VIS[0],    VIS[1],    [0,0.4,1,2.4,2.5,2.6,4.9,5,5.1,6,9.9,10,30,67.3], 10, null);
    run("aqi",    AQI[0],    AQI[1],    [0,12,48,50,51,63,80,100,101,120,150,151,175,200,260,999], 200, null);
    console.log(JSON.stringify(out));
    """
    ax = node(harness)

    for key, rungs, cap in (("precip", ax["rungs"]["precip"], None),
                            ("precip (metric)", ax["rungs"]["precip (metric)"], None),
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
    for key in ("precip", "precip (metric)"):
        lied = [(r["top"], lab) for r in ax[key] for i, lab in enumerate(r["labels"])
                if abs(float(lab) - i * r["step"]) > 1e-9]
        check("%s: every label equals its gridline value" % key, not lied, str(lied[:3]))
    # 75 mm does the 3 in rung's job: a real Miami week, 2.08 in = 52.8 mm, fills most of the row
    check("precip (metric): the 52.8 mm Miami week lands on 75, not 125",
          [x for x in ax["precip (metric)"] if x["max"] == 52.8][0]["top"] == 75)

    # The tide axis is no ladder - it brackets the data and cuts the span into four equal steps -
    # but the same lie was open to it: a 3 ft span steps 0.75, and at one fixed decimal its -0.25
    # gridline printed "-0.3". Sweep spans of every width mod 4, either side of the zero line, in
    # feet and in metres (the metric axis rounds out to 0.4 m, so every quarter prints at one
    # decimal - and its float noise must never print a zero line as "-0.0").
    def tide_sweep(table, spans):
        return node(extract(src, "tideAxis") + "\n" + units + ";var U=" + table + ", S=" + json.dumps(spans) + ";"
                    "console.log(JSON.stringify(S.map(function (p) {"
                    "  var t = tideAxis(p[0], p[1], U.tidePad, U.tideGrain), g = [];"
                    "  for (var v = t[0]; v <= t[1] + 1e-9; v += t[2]) g.push([v, t[3](v)]);"
                    "  return { lo: p[0], hi: p[1], bottom: t[0], top: t[1], g: g }; })));")
    feet = [(lo, round(lo + w, 2)) for lo in (-3.3, -1.2, -0.5, 0, 0.3, 1.1)
            for w in (0.05, 0.3, 0.9, 1.7, 2.0, 2.6, 3.4, 5.5, 8.2, 11.9, 15.3, 22.7)]
    metres = [(lo, round(lo + w, 3)) for lo in (-1.0, -0.37, -0.15, 0, 0.09, 0.34)
              for w in (0.015, 0.09, 0.27, 0.52, 0.61, 0.79, 1.04, 1.68, 2.5, 3.63, 4.66, 6.92)]
    for name, tx in (("tide", tide_sweep("UNITS_IMPERIAL", feet)),
                     ("tide (metric)", tide_sweep("UNITS_METRIC", metres))):
        lied = [(t["lo"], t["hi"], lab) for t in tx for v, lab in t["g"] if abs(float(lab) - v) > 1e-9]
        check("%s: every label equals its gridline value" % name, not lied, str(lied[:3]))
        wrong = [(t["lo"], t["hi"]) for t in tx if not (t["bottom"] <= t["lo"] and t["top"] >= t["hi"])]
        check("%s: axis brackets the data" % name, not wrong, str(wrong[:3]))
        wrong = [(t["lo"], t["hi"], len(t["g"])) for t in tx
                 if len(t["g"]) != 5 or abs(t["g"][-1][0] - t["top"]) > 1e-9]
        check("%s: five gridlines, the top one drawn" % name, not wrong, str(wrong[:3]))
        if name == "tide":
            check("tide: the -0.25 gridline reads -0.25, not -0.3",
                  "-0.25" in [lab for t in tx if (t["lo"], t["hi"]) == (-0.5, 1.5) for _, lab in t["g"]])
        else:
            odd = [lab for t in tx for _, lab in t["g"] if not re.match(r"^-?\d+\.\d$", lab) or lab == "-0.0"]
            check("tide (metric): one decimal on every label, and never -0.0", not odd, str(odd[:3]))

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
            units + "var HOURS=4, i, U=UNITS_IMPERIAL;"
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
        # Metric caps at 10 km, and has to convert BEFORE it caps: 7 mi is 11.3 km, so it must read
        # 10 - capping first would let 11.3 through, and forgetting to convert would read 7.
        rm = node(units + "var HOURS=3, i, U=UNITS_METRIC; var data={vis:[2.0,7.0,null]};"
                  + vis_block.group(1) + "\nconsole.log(JSON.stringify(vmax));")
        check("metric: the scan converts to km, then caps at 10", rm == 10, "vmax=%s" % rm)
        check("capped AQI 260/999 land on the 200 rung",
              all(x["top"] == 200 for x in ax["aqi"] if x["max"] in (260, 999)))

    # ---------------------------------------------------------------- units
    u = node(units + r"""
    var I = UNITS_IMPERIAL, M = UNITS_METRIC;
    console.log(JSON.stringify({ keysI: Object.keys(I).sort(), keysM: Object.keys(M).sort(),
      t: [M.t(32), M.t(212), M.t(-40)], conv: [M.s(10), M.p(1), M.d(1), M.h(1)],
      missing: [M.t(null), M.s(null), M.p(null), M.d(null), M.h(null)], undef: M.t(undefined) === undefined,
      same: [I.t(71.2), I.s(12.9), I.p(0.14), I.d(9.4), I.h(-1.5)], elev: [I.elev(100), M.elev(100)] }));""")
    # two whole tables, like the palette: an entry missing from one prints "undefined" on the page
    check("units: both tables carry the same entries", u["keysI"] == u["keysM"],
          str(sorted(set(u["keysI"]) ^ set(u["keysM"]))))
    check("units: F -> C at 32, 212 and -40",
          all(abs(a - b) < 1e-9 for a, b in zip(u["t"], [0, 100, -40])), str(u["t"]))
    check("units: mph -> km/h, in -> mm, mi -> km, ft -> m",
          all(abs(a - b) < 1e-9 for a, b in zip(u["conv"], [16.09344, 25.4, 1.609344, 0.3048])), str(u["conv"]))
    check("units: a missing hour stays missing, not -17.8", u["missing"] == [None] * 5 and u["undef"])
    check("units: imperial passes readings through untouched", u["same"] == [71.2, 12.9, 0.14, 9.4, -1.5])
    check("units: elevation arrives in metres",
          abs(u["elev"][0] - 328.084) < 1e-9 and u["elev"][1] == 100, str(u["elev"]))
    # bw_units is shared by three pages and read before anything is drawn: only the exact stored
    # string means metric, and anything else - absent, garbage, a different case - is the default
    stored = ["metric", "Metric", "imperial", None, 1, True, {}, ["metric"]]
    got = node(extract(src, "fmtIn") + ";var BLOCK=" + json.dumps(units_block(src)) + ", S=" + json.dumps(stored) + ";"
               "console.log(JSON.stringify(S.map(function (s) {"
               "  var load = function () { return s; }; eval(BLOCK); return U === UNITS_METRIC; })));")
    check('units: only a stored "metric" means metric; anything else is imperial',
          got == [True] + [False] * (len(stored) - 1), str(got))
    # weather365 carries its own copy of the tables (one file per page, DESIGN.md section 11), so
    # hold that copy to the same factors and the same both-tables-line-up rule
    src365 = open(os.path.join(ROOT, "weather365", "index.html"), encoding="utf-8").read()
    h = node(unit_tables(src365) + ";var I = UNITS_IMPERIAL, M = UNITS_METRIC;"
             "console.log(JSON.stringify({ keysI: Object.keys(I).sort(), keysM: Object.keys(M).sort(),"
             " conv: [M.t(212), M.p(1), M.elev(100), I.elev(100)], missing: M.t(null) }));")
    check("weather365: both unit tables carry the same entries", h["keysI"] == h["keysM"],
          str(sorted(set(h["keysI"]) ^ set(h["keysM"]))))
    check("weather365: converts like the forecast pages",
          all(abs(a - b) < 1e-9 for a, b in zip(h["conv"], [100, 25.4, 100, 328.084])) and h["missing"] is None,
          str(h["conv"]))

    # ---------------------------------------------------------------- fallback predicate
    # Every one of these is a real response shape observed from Open-Meteo: the 400s and the 429s
    # on 2026-08-22, the two HTTP 200 bodies on 2026-09-16. Only the shapes that mean "off NBM's
    # grid" may come back "coverage", and only the ones where NBM could not serve the request may
    # come back "unavailable". What must still come back "" is the short list that matters: a
    # request we broke ourselves, because quietly serving the 25 km inland forecast instead is the
    # bug the move to NBM exists to fix; and a 429, which is the one failure where falling back
    # makes things worse rather than better.
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
        # 429 sits below the 5xx test on purpose and must never be folded into it: the limit is
        # per origin, so the ECMWF retry rate-limits too and the reader sees the error anyway, one
        # wasted round trip later and with more pressure on the limit. Ken's call, 2026-09-18.
        (429, "Too many concurrent requests", "", "", "rate limit (concurrent)"),
        (429, "Minutely API request limit exceeded. Please try again in one minute.", "", "", "rate limit (minutely)"),
        # 5xx and a fetch that never reached anything both mean NBM could not serve this, so ECMWF
        # answers and the footer says NBM was unavailable. Ken's call, 2026-09-18.
        (500, "", "", "unavailable", "upstream 5xx"),
        (502, "", "", "unavailable", "upstream 502"),
        (503, "", "", "unavailable", "upstream 503"),
        (0,   "", "", "unavailable", "network reject (status 0)"),
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
    # What a real fetch rejection actually looks like: a TypeError with no status property at all,
    # not the status 0 the table above can express. The table builds its objects by hand, so this
    # is the one shape it cannot reach and the one the browser will really hand us.
    check("fallback %-32s -> unavailable" % "fetch TypeError (no status key)",
          node(fallback_fn + ";var e=new TypeError('Failed to fetch');"
               "console.log(JSON.stringify(backboneFallback(e)))") == "unavailable")

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
