# Weather Chart - Design Doc

Personal weather site for Ken Clements. Built August 2026. This document is the source of truth for how the site is put together; update it whenever the site changes.

**Status: LIVE** at kenclements.com. Personal, non-commercial use only (this matters for data licensing, see Data Sources).

---

## 1. Pages and URLs

| URL | What it is | Source folder |
|-----|------------|---------------|
| kenclements.com/weather10 | 10 Day Weather Forecast | `weather10/` |
| kenclements.com/weather3 | 3 Day Weather Forecast (same page, 72 hours) | `weather3/` (generated, see §4) |
| kenclements.com/weather365 | Average Year: 10-year daily historical averages | `weather365/` |
| kenclements.com | Redirects to Ken's LinkedIn profile | `index.html` |
| /weather, /weather1, /weather2 | Redirect stubs to the pages above (old names) | `weather/`, `weather1/`, `weather2/` |

Page navigation (#pagenav) sits under the GPS-coordinates line on every page: all three options always show as 34px buttons, in order "3 Day Forecast · 10 Day Forecast · Historical". The current page (span.here) is the inverse of the other two: blue fill with white text, inert; the links are white with blue text. On phones (under 600px) the forecast labels shorten to "3 Day" / "10 Day" (the word " Forecast" lives in a span.fc hidden by media query; "Historical" never shortens) and the three buttons become equal width (`flex: 1 1 0`, centered text), together spanning the full content width responsively. Naming rule: always "N Day Forecast", never hyphenated "N-day", anywhere on the site.

The whole site is robots-blocked (`robots.txt` Disallow all + `noindex` meta on every page). Browser tab identity: "City · Weather Chart" (forecast pages) and "City · Average Year" (historical).

## 2. Hosting and deploy

- GitHub Pages, repo `kenclem7/kenclem7.github.io` (public, required for free Pages), branch `main`, legacy build from root. `.nojekyll` present.
- **Deploy = push to main.** Pages rebuilds in under a minute. No build step, no bundler; every page is one self-contained HTML file with inline CSS and JS.
- Custom domain via `CNAME` file; https enforced. DNS lives at Hover: four GitHub Pages A records on the apex (185.199.108-111.153) plus `www` CNAME to `kenclem7.github.io`. Hover also keeps its default MX records (email plumbing, unrelated to the site).
- Local dev: `py -m http.server 3462 --directory kenclements-site` (launch.json entry `kenclements-site`), pages at `localhost:3462/weather10/` etc.
- Layout note learned the hard way: chart width leaves 2px slack under the container, otherwise Windows fractional display scaling (125%) creates a sub-pixel overflow and a useless scrollbar.

## 3. Data sources (all free)

| Source | Used for | License notes |
|--------|----------|---------------|
| Open-Meteo forecast API, `models=ecmwf_ifs025` | 10-day backbone: temp, feels-like, precip, weather code, cloud, wind | CC BY 4.0, **non-commercial tier**. Attribution link in every footer. If the site ever moves to a business property, the $29/mo commercial plan is required. |
| Open-Meteo forecast API, best-match (no models param) | Precip probability (ensemble), **visibility** (ECMWF publishes none - verified, all nulls), sunrise/sunset, current conditions block (15-minute data incl. is_day) | same |
| Open-Meteo forecast API, `models=gfs_hrrr` | HRRR short-range overlay, first ~2 days (orange dashes, toggleable) | same |
| Open-Meteo archive API (ERA5) | weather365: one fetch of 10 years of daily history per city | same |
| Open-Meteo geocoding API | Location search box | same |
| NOAA CO-OPS (tidesandcurrents.noaa.gov) | Tide predictions (hourly + high/low events) and current predictions | US government work, public domain, CORS-enabled. No key. |
| OpenStreetMap tiles + Leaflet 1.9.4 (unpkg CDN) + Nominatim reverse geocoding | "Use Map" location picker | Free, no key, no account. OSM attribution shown on the map. Leaflet lazy-loads on first open. |
| BigDataCloud reverse-geocode-client | Naming water clicks on the map (body of water + state when available) | Free client API, no key, CORS-enabled. Only called when Nominatim finds no locality. |

## 4. The two forecast pages share one source

`weather3/index.html` is **generated from** `weather10/index.html`. Never hand-edit weather3. After any weather10 change, regenerate:

```python
s = open('weather10/index.html', encoding='utf-8').read()
# asserts: 1x 'HOURS = 240', 2x 'forecast_days: 10', 2x '10 Day Weather Forecast'
s = s.replace('HOURS = 240', 'HOURS = 72')
s = s.replace('forecast_days: 10', 'forecast_days: 3')
s = s.replace('10 Day Weather Forecast', '3 Day Weather Forecast')
s = s.replace('<a href="/weather3/">3 Day<span class="fc"> Forecast</span></a><span class="here">10 Day<span class="fc"> Forecast</span></span>',
              '<span class="here">3 Day<span class="fc"> Forecast</span></span><a href="/weather10/">10 Day<span class="fc"> Forecast</span></a>')
# the ".fc" span holds the word " Forecast", hidden under 600px so phones read "3 Day" / "10 Day"
open('weather3/index.html', 'w', encoding='utf-8', newline='').write(s)
```

Everything else (DAYSN = HOURS/24) derives at runtime. The two pages share all localStorage state, so a city or layout chosen on one appears on the other.

## 5. Forecast page anatomy (weather10 / weather3)

**Header row:** CSS grid `1fr auto 1fr` so the current-conditions card sits on the true page centerline (title left, search right; under 900px it stacks to one column). Columns are bottom-aligned (`align-items: end`): the page nav, the conditions card, and the recents pull-down share one bottom line. Page nav renders as buttons (14px/600, line-height 16px so they stand exactly 34px tall like the search input, Use Map, and recents pull-down): white with blue text for the two links, and the exact inverse (blue fill, white text) for the current page, which is inert. The card: bordered, big temp, icon with day/night variants, condition, feels-like + wind + gusts, next sun event as "sunset 8:21pm" / "sunrise 6:06am". Search box has the **Use Map** button beside it; the page-nav row lives under the coordinates line in the title block. Cascade note: the narrow-screen @media block must stay AFTER the base header rules or it loses the tie.

**Location entry, three ways:**
1. Search box: Open-Meteo geocoding, dropdown, Enter picks first.
2. **Use Map**: modal with OSM map, click drops a pin, "Use this location". Naming chain: Nominatim locality for land clicks; when no locality comes back (water), BigDataCloud's free reverse-geocode-client names the body of water and the result reads "Pacific Ocean near Avalon" style, with the "near" harbor taken from the nearest NOAA tide station within 80 mi (first comma-part of the station name). Far offshore it is just the water name; if everything fails, the coordinates stand. Never trust Nominatim's `j.name` (it returns "United States" for territorial water - the original bug).
3. Share links: `?lat&lon&name&admin1&cc&elev` params override the saved city without touching it. The **share** button (locmeta row, left of refresh) copies such a link for the current view.
4. **GPS button** (square, target icon, right of Use Map, 34px like its neighbors): browser geolocation -> the same pickOnMap naming chain (works with the map modal closed via the lmark guard) -> selects when naming settles (`mapPick.naming` promise, 6s cap; `naming` is deleted before the pick is saved so no promise junk lands in localStorage). Needs https or localhost; errors surface in the status line.

Recents are a pull-down under the search row (#recwrap, exactly the width of input + Use Map): the button shows the active city with a caret, the menu lists up to 8 recents (active row highlighted, per-row × remove), shared across all three pages via `bw_recents`. Outside click or Escape closes it.

**Day strip:** date + hi/lo (14px), icon emoji, condition, precip, sunrise/sunset row ("↑6:05am  ↓8:21pm", non-breaking spaces, amber #c08a12). Strip height 136.

**Chart rows, default order:** TEMPERATURE, WIND, CLOUDS, VISIBILITY, PRECIP, TIDE.

| Row | Contents |
|-----|----------|
| Temperature | temp (red) + feels-like (purple), HRRR dashes |
| Wind | speed line light blue #93c4ec with navy #14396e direction arrows every 3h **pointing where the wind is going** (tooltip says "from"); gusts dashed gray. **Axis tops out at the exact max drawn gust** (Ken's explicit rule, do not "nice-round" it) with whole-number gridlines below. |
| Clouds | cloud cover gray area + precip chance blue area (ensemble), HRRR dashes |
| Visibility | line (not area - it pins at 10+ mi most days), 0-10 mi axis, orange dashed line at 1 mi over a tan "fog" band. From best-match model. |
| Precip | accumulation area + hourly precip line |
| Tide | NOAA hourly tide curve (ft MLLW), every high/low labeled with height + time; **current overlaid** in purple on its own ± scale around a dotted zero (+flood / -ebb, knots), built by cosine-interpolating NOAA's MAX_SLACK events. Legend names both stations and their distances. Row only exists when a tide station is within 60 mi (currents within 25 mi). Many stations return the literal string "Currents are weak and variable" - shown in the legend as NOAA's answer. |

Station lookup uses `data/tide-stations.json` and `data/current-stations.json`: pre-trimmed copies of NOAA's station metadata (340KB total vs NOAA's 5.6MB). Regenerate occasionally from `api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions|currentpredictions` keeping `[id,name,lat,lng]` / `[id,bin,name,lat,lng]`.

**Chart chrome:** night shading (dusk to dawn, #dce6f2 at .35) instead of alternating day bands; darker day-boundary lines #aeb6c0; black "now" line; orange crosshair + 19px tooltip showing every row's value for the hovered hour (sun times, temp, wind, cloud/chance, visibility incl. "(fog)", accum, tide + current).

**User layout controls (persisted per device):**
- **Reorder:** each row has a 13px black uppercase title + dot handle in the left margin (PADL 64). Drag by title or dots; the handle rides the pointer, the in-flight row is tinted blue with a dashed outline, others slide aside live. Double-click a handle: default order.
- **Resize:** grip at each row's bottom-right; drag down to grow. Defaults are minimums. Double-click a grip: default sizes.

## 6. Historical page anatomy (weather365)

- **Window: the last 10 full years (2016-2025).** Deliberately 10y, not 30y climate normals (weather is shifting). **Bump `YEAR_START`/`YEAR_END`/`YEARS_LABEL` each January.**
- 365 x-axis points (Feb 29 dropped). One ERA5 archive fetch per city, aggregated client-side, cached in `bw2norm3:lat,lon` (LRU 6). Schema changes bump the `bw2norm` suffix and the boot purge guard.
- Temperature chart: avg high/low lines + pink band, plus an **outer extremes band**: each date's single highest/lowest reading of the 10 years, with the **year** in the tooltip ("▲ 103° highest (2021)"). Kirkland Jun 28 showing the 2021 heat dome is the sanity check.
- Precipitation chart: daily average area + dark smoothed weekly-average curve (7-day circular mean then triangular kernel). Tooltip shows the day and the month total.
- Same header kit as the forecast pages (search, map, share, recents, spinner). No reorder/resize (two fixed rows).

## 7. localStorage keys

| Key | Meaning |
|-----|---------|
| `bw_current` / `bw2_current` | Selected city, forecast pages / historical page |
| `bw_recents` | Shared recents list (max 8) |
| `bw_hrrr` | HRRR overlay toggle |
| `bw_sizes` | Row heights (forecast pages) |
| `bw_order` | Row order (forecast pages) |
| `bw2norm3:lat,lon` + `bw2norm3_keys` | Historical per-city cache + LRU list |

Share-link visits never write `bw_current`, so opening someone's link does not clobber your saved city.

## 8. Known limitations / honest notes

- Tide/current stations are straight-line nearest: Kirkland gets Elliott Bay (Sound water) even though Moss Bay is lake water behind the Locks. The legend always names the station and distance so the mismatch is visible.
- No waves, no Small Craft Advisories, no live buoy observations yet (candidate next features; NWS/NOAA feeds are free and public domain).
- Visibility is a model estimate from the blended model, not ECMWF, and fog is the hardest thing any model predicts.
- Nominatim is rate-limited (courtesy service): fine for one click at a time, never for bulk lookups.
- Wind is in mph to match Wunderground habits; knots has been discussed but not built.

## 9. House copy rules

- "N Day Forecast" (no hyphen, capital D), "homepage" not "landing page", lowercase tight am/pm on sun times ("6:05am"), no em dashes in copy.
