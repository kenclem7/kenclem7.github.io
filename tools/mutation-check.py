#!/usr/bin/env python3
"""Checks the tests, not the code: breaks weather10/index.html on purpose, one line at a time,
and confirms the assertion that should have caught it is the one that goes red.

  py tools/mutation-check.py          run every mutation, restore the page, report

DESIGN.md section 9 asks for this by hand for any case added to the suite. This is that, written
down, because doing it by hand is how you convince yourself an assertion works and skipping it is
how the suite quietly stops meaning anything. It earned its keep the day it was written: of the
seven mutations below, two were wrong on the first run - one needle never matched because the
working tree is CRLF and the needle was LF, and one "widened" a regex to something that happened
not to match the test fixture either. A mutation that fails to go red is telling you about YOUR
MUTATION first and the assertion second. Read it that way before you edit the suite.

It is deliberately NOT in CI, for the same reason the --live half is not. The needles below are
exact source lines, so any legitimate edit to one of them fails this with "needle not unique" and
would redden a perfectly good commit. Run it by hand when you touch the suite or the predicate.

THE PAGE IS MUTATED IN PLACE and restored in a finally, then asserted byte-for-byte at the end.
Nothing here writes weather3, so if this dies hard enough to skip the restore, run
`py tools/gen-weather3.py` after putting weather10 back."""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "weather10", "index.html")
TEST = os.path.join(ROOT, "tools", "test-weather.py")

# (label, needle, replacement, the check-name fragments that MUST go red)
MUTATIONS = [
    ("drop the nan-coordinate clause",
     '  if (e.status === 200 && /"(?:latitude|longitude)"\\s*:\\s*nan/.test(e.body || "")) return "coverage";\n',
     "",
     ["out of coverage (nan coords)"]),
    ("drop the not-JSON-200 clause",
     '  if (e.status === 200 && e.body) return "unavailable";\n',
     "",
     ["upstream stall", "nan in the data, not the coords"]),
    ("drop the 5xx clause",
     '  if (e.status >= 500) return "unavailable";',
     "",
     ["upstream 5xx", "upstream 502", "upstream 503"]),
    ("drop the no-status clause",
     '  if (!e.status) return "unavailable";',
     "",
     ["network reject (status 0)", "fetch TypeError (no status key)"]),
    # The one that matters most: 429 must not get folded in with the 5xx. Falling back there fires
    # a second request at an API that just said to slow down, and the limit is per origin.
    ("fold 429 into the 5xx clause",
     "  if (e.status >= 500) return \"unavailable\";",
     "  if (e.status >= 429) return \"unavailable\";",
     ["rate limit (concurrent)", "rate limit (minutely)"]),
    ("widen the 5xx clause to every 4xx as well",
     "  if (e.status >= 500) return \"unavailable\";",
     "  if (e.status >= 400) return \"unavailable\";",
     ["typo'd model", "bad variable", "missing latitude", "lat out of range", "forecast_days"]),
    ("widen nan test to any nan in the body",
     '/"(?:latitude|longitude)"\\s*:\\s*nan/',
     "/nan/",
     ["nan in the data, not the coords"]),
    ("let any 200 mean out of coverage",
     '  if (e.status === 200 && /"(?:latitude|longitude)"\\s*:\\s*nan/.test(e.body || "")) return "coverage";\n',
     '  if (e.status === 200) return "coverage";\n',
     ["upstream stall", "nan in the data, not the coords"]),
    ("stop rethrowing a 400 we caused",
     '  if (e.status === 400 && (e.reason || "").indexOf("No data is available") === 0) return "coverage";\n',
     '  if (e.status === 400) return "coverage";\n',
     ["typo'd model", "bad variable", "missing latitude", "lat out of range", "forecast_days"]),
    ("usableBackbone stops checking the time axis is populated",
     "return !!(j && j.hourly && j.hourly.time && j.hourly.time.length);",
     "return !!(j && j.hourly);",
     ["hourly present but empty", "hourly with no time axis"]),
    ("one footer label for both fallbacks",
     '                  unavailable: "ECMWF model (NBM unavailable)" };',
     '                  unavailable: "ECMWF model (outside NBM coverage)" };',
     ["NBM unavailable names ECMWF and why", "the two fallbacks do not read the same"]),
]


def run_suite():
    """-> set of failing check names. The suite prints '  FAIL  <name>' and may append '  <- detail'."""
    r = subprocess.run([sys.executable, TEST], capture_output=True, text=True)
    return set(re.findall(r"^  FAIL  (.+?)(?:  <- |$)", r.stdout, re.M))


def main():
    with open(PAGE, encoding="utf-8", newline="") as f:
        pristine = f.read()
    # The working tree holds CRLF while the committed bytes are LF (core.autocrlf, the line-ending
    # trap in DESIGN.md section 4), so needles written with \n match nothing until this normalizes.
    # Getting this wrong does not error - every mutation just silently skips.
    nl = "\r\n" if "\r\n" in pristine else "\n"
    flat = pristine.replace("\r\n", "\n")

    baseline = run_suite()
    if baseline:
        sys.exit("the suite is already red before mutating, fix that first: %s" % sorted(baseline))
    print("baseline: green\n")

    bad = 0
    for label, old, new, want in MUTATIONS:
        if flat.count(old) != 1:
            print("SKIP  %-56s needle matched %d times, not 1" % (label, flat.count(old)))
            bad += 1
            continue
        with open(PAGE, "w", encoding="utf-8", newline="") as f:
            f.write(flat.replace(old, new).replace("\n", nl))
        try:
            failed = run_suite()
        finally:
            with open(PAGE, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)

        missed = [s for s in want if not any(s in name for name in failed)]
        # weather3 is a byte-copy, so its tripwire fires on every mutation by construction
        collateral = sorted(n for n in failed
                            if "faithful copy" not in n and not any(s in n for s in want))
        print("%-5s %-56s %d red%s" % ("PASS" if not missed else "FAIL", label, len(failed),
                                       "" if not missed else "   MISSED " + str(missed)))
        if collateral:
            print("      also red, confirm this is expected: %s" % collateral)
        if missed:
            bad += 1

    with open(PAGE, encoding="utf-8", newline="") as f:
        if f.read() != pristine:
            sys.exit("PAGE NOT RESTORED - run: git checkout weather10/index.html")
    print("\npage restored byte-for-byte; %d of %d mutation(s) not caught"
          % (bad, len(MUTATIONS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
