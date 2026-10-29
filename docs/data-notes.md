# Data notes

What we verified about the two Elexon datasets the challenge specifies, and
what that means for the app. Every statement below is either quoted from
Elexon's documentation or observed in real API responses (marked
**documented** or **observed**). Anything not verified is marked **unverified**.

- First checked: 2026-10-28. Re-checked and extended: 2026-10-29.
- Raw responses and rendered documentation pages are saved in `data/raw/`
  (gitignored). File names are listed in the last section.
- No other dataset is used.

## Sources consulted

| Source | What it gave us |
|---|---|
| Endpoint docs linked in `docs/requirements.md`: `https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream` and `.../WINDFOR/stream` | Parameters, response example, error codes. These pages need JavaScript, so they were rendered with headless Chrome. |
| OpenAPI spec `https://data.elexon.co.uk/swagger/v1/swagger.json` | Exact parameter names and types, response schema, nullability |
| Elexon Insights pages `https://bmrs.elexon.co.uk/wind-generation` and `https://bmrs.elexon.co.uk/generation-by-fuel-type` | What each dataset covers, units, publication schedule |
| Real API responses (samples, then full January) | Resolution, timezones, versions, duplicates, gaps, limits |

## Verified endpoints

Base URL: `https://data.elexon.co.uk/bmrs/api/v1`. Both endpoints are `GET` and
return a plain JSON list of rows (not wrapped in `{"data": ...}`).

### Actuals: FUELHH stream

`GET /datasets/FUELHH/stream?settlementDateFrom=2026-01-01&settlementDateTo=2026-01-01&fuelType=WIND`

| Parameter | Type | Filters on |
|---|---|---|
| `settlementDateFrom`, `settlementDateTo` | date, exactly `yyyy-MM-dd` | **target** (the settlement day the half-hour belongs to) |
| `publishDateTimeFrom`, `publishDateTimeTo` | date-time | **publication** time |
| `settlementPeriod` | list of integers | target period (1 to 48) |
| `fuelType` | list of strings | fuel type, e.g. `WIND` |

- **Documented and observed:** settlement-date and publish-time filters cannot
  be combined. Doing so returns HTTP 400: *"The Settlement Date fields cannot
  be set when a Publish Date field is set."*
- **Observed:** fuel types returned without a filter: BIOMASS, CCGT, COAL,
  INTELEC, INTEW, INTFR, INTGRNL, INTIFA2, INTIRL, INTNED, INTNEM, INTNSL,
  INTVKL, NPSHYD, NUCLEAR, OCGT, OIL, OTHER, PS, WIND. We keep **only `WIND`**:
  the server filters it, and the cleaning code checks it again.

### Forecasts: WINDFOR stream

`GET /datasets/WINDFOR/stream?publishDateTimeFrom=2026-01-01T00:00:00Z&publishDateTimeTo=2026-01-01T12:00:00Z`

| Parameter | Type | Filters on |
|---|---|---|
| `publishDateTimeFrom`, `publishDateTimeTo` | date-time | **publication** time only |

- **Documented and observed:** with no filter, only the latest publication is
  returned (one publication, 73 rows).
- There is **no filter on target time**. To get every forecast for January
  delivery days, we fetch by publish time and filter `startTime` afterwards.
- We keep `startTime`, `publishTime` and `generation` exactly.

### Errors

- **Documented:** 400 for bad parameters, 429 for too many requests, 500 for
  server errors.
- The download script raises an error on any non-200 response, so a failed
  request never becomes a silent gap.

## Field meanings, with examples

FUELHH row (observed):
`{"dataset":"FUELHH","publishTime":"2026-01-02T00:00:00Z","startTime":"2026-01-01T23:30:00Z","settlementDate":"2026-01-01","settlementPeriod":48,"fuelType":"WIND","generation":15538}`

| Field | Meaning |
|---|---|
| `startTime` | Start of the half-hour the value describes (UTC) |
| `generation` | **Average MW** over that half-hour (documented: "average MW values over 30 minutes"). Integer. |
| `publishTime` | When Elexon published the row. Observed 30 minutes after `startTime`, i.e. once the half-hour has ended. |
| `settlementDate`, `settlementPeriod` | GB settlement day and period 1 to 48. Observed to match `startTime` exactly in January. |

WINDFOR row (observed):
`{"dataset":"WINDFOR","publishTime":"2026-01-01T09:30:00Z","startTime":"2026-01-02T12:00:00Z","generation":17739}`

| Field | Meaning |
|---|---|
| `publishTime` | When NESO issued this forecast (UTC). One publication = many rows sharing this value. |
| `startTime` | The hour being forecast (UTC) |
| `generation` | Forecast wind generation for that hour. Documented as "a single MW figure"; the endpoint page itself states no unit. Integer. |

## Publication time vs target time

These are different clocks, and mixing them up is the main way to get this
analysis wrong.

- **`startTime` is the target time:** the hour or half-hour *being described*.
- **`publishTime` is the publication time:** the moment the number *became
  known*.
- A single target hour has **many forecasts**, one per publication. For
  example, `2026-01-02T12:00Z` was forecast by every publication from 31 Dec
  onwards. Later forecasts are usually closer to reality, but a trader at the
  cutoff could only have seen the ones published at or before the cutoff.
- That's why the app selects by `publishTime <= cutoff`, then takes the
  latest per target hour. Choosing by `startTime`, or by "the latest forecast
  in the database", would leak information from after the decision.
- **Lead time** = `startTime - publishTime`. **Observed:** in January's data
  it ranges from -25.5 h to +66.5 h. The 4,201 rows with a **negative** lead
  time describe hours *before* their own publication, so they aren't real
  forecasts. They can never be selected: a delivery day always starts after
  the decision cutoff, so every forecast the app uses has a positive lead time
  (14.5 to 37.5 h at the 10:00 cutoff).

## Resolution, timezones and versions

| Check | FUELHH | WINDFOR |
|---|---|---|
| Resolution (observed) | 30 minutes, 48 per settlement day | 1 hour, always on the hour |
| Timezone (observed) | UTC, every timestamp ends in `Z` | UTC, every timestamp ends in `Z` |
| Multiple versions (observed) | No: one row per `startTime` in January | **Yes:** every publication is kept (280 publications from 28 Dec 2025 to 31 Jan 2026) |
| Rows per request unit | 48 per settlement day | 73 per publication |

- WINDFOR publications per day (**observed**): 8 every day, normally at 02:30,
  04:30, 07:30, 09:30, 11:30, 15:30, 18:30 and 22:30 UTC. On 15 Jan the 11:30
  publication came at **12:25**.
- **Documented** times ("03:30, 05:30, 08:30, 10:30, 12:30, 16:30, 19:30 and
  23:30") are **one hour later** than the real `publishTime` values in
  January. **Unverified** why. The app always uses the real `publishTime` and
  never assumes a schedule.
- WINDFOR horizon: **documented** as "from 20:00 (GMT) on the current day (D)
  to 20:00 (GMT) (D+2)". **Observed** as 73 hourly values from 21:00 UTC on
  the day *before* publication to 21:00 UTC two days *after*. The documented
  and observed windows differ; we rely on what is observed.
- Timezone handling: everything is parsed as UTC and converted to
  Europe/London only for day boundaries and display.

## Duplicates and missing data

Checked on the full January downloads (1,584 FUELHH rows; 20,440 WINDFOR rows):

| Check | FUELHH | WINDFOR |
|---|---|---|
| Missing fields (key absent) | 0 | 0 |
| Null values | 0 | 0 |
| Duplicate keys (`startTime` / `publishTime + startTime`) | 0 | 0 |
| Negative generation | 0 | 0 |
| Generation range (MW) | 1,695 to 17,805 | 2,051 to 21,353 |
| Late publications | 4 rows published 56 to 145 min after start (instead of 30) | see 12:25 above |

- **Documented:** the schema marks **every field as nullable**, including
  FUELHH `startTime`. January has no nulls, but the cleaning code handles
  them anyway:
  - rows without a usable timestamp, or off the 30-minute / hourly grid,
    are removed **and counted** in the manifest;
  - a null, non-numeric or non-finite `generation` becomes missing (never 0)
    and is counted; negative values are kept but flagged;
  - exact duplicates are removed; **conflicting duplicates are reported**. An
    actual is resolved only by a later revision; anything else becomes
    missing.

## Request-size and date-range limits

- **Documented:** no range limit is stated for either stream endpoint. Many
  other Elexon endpoints do state one (for example 7, 92 or 367 days). The
  Insights wind page says its export covers "periods of up to two months".
- **Observed:**
  - one WINDFOR request covering a 35-day publish range returned 20,440 rows
    (2.3 MB, 4.3 s);
  - one FUELHH request covering 33 settlement days returned 1,584 rows;
  - both were **identical** to the week-by-week downloads, so nothing was cut
    off.
- **Our choice:** still download in 7-day chunks. It's cheap, keeps each
  request small, and is safe if an undocumented limit exists or is added
  later.
- **Documented:** 429 *Too many requests*. The pipeline retries 429 and 5xx
  responses up to 4 attempts with waits that grow each time; a full month is
  10 requests.

## Comparability between the two datasets

The challenge asks us to score WINDFOR against FUELHH WIND. Based on
Elexon's documentation, they are **broadly comparable**, with known limits:

1. **Both cover the same population, roughly.**
   - **Documented:** WINDFOR is a forecast "for wind farms which are visible
     to the ESO and have operational metering".
   - **Documented:** FUELHH comes from "Operational Metering for BMUs
     connected to the transmission system", and its wind figure excludes
     "embedded generation and wind farms which do not have Operational
     Meters". NESO estimates that metered wind is about 82% of GB wind (2025).
   - So **neither dataset is total GB wind generation.** The app must not
     present these numbers as total national wind.
   - **Documented:** Elexon's own wind page compares WINDFOR against outturn
     "derived from the Generation by Fuel Type data", which is the same pairing
     we use.
2. **Different resolutions.** WINDFOR is hourly; FUELHH is half-hourly
   averages. **Decided:** the forecast for hour `T` is compared with the mean of
   the half-hours starting at `T` and `T+30min`. If either is missing, the hour
   is missing.
3. **Point value or hourly average?** It is **unverified** whether a WINDFOR
   value is an hourly average or a value at the start of the hour. The docs
   say only "hourly forecast". Our averaging assumes it represents the hour.
4. **Actuals may include estimates.** **Documented** for the wind page outturn:
   "Where available, real time telemetry is used, where it is not estimates of
   outturns are used."
5. **Systematic over-forecast (observed, not explained).** At the 10:00 cutoff,
   January forecasts were on average about **+1,730 MW above** actuals. Two
   possible causes are **unverified**: wind farms being curtailed for grid
   reasons (which would lower metered output) and scope differences between
   the two datasets. We report the bias but do not claim a cause.
6. **Units.** FUELHH is documented as average MW. WINDFOR is documented as MW
   on the Insights page, though not on the endpoint page. Values are integers
   of the same magnitude in both.

## What this means for the app

- **Default cutoff 10:00 Europe/London** (= 10:00 UTC in January). The latest
  eligible publication is normally 09:30 UTC that day.
- **Early cutoffs leave gaps, by design.** With a cutoff before 02:30, the
  latest publication (22:30 the evening before) reaches only 21:00 UTC of the
  delivery day. So the last 2 hours have **no eligible forecast**: coverage is
  22 of 24 hours (91.7%) on every January day. These hours are shown as
  missing, never filled in.
- **Expected intervals per delivery day** are counted from Europe/London day
  boundaries (23, 24 or 25 hours), never hard-coded.
- **Fetch ranges** (derived from `--decision-month 2026-01`):
  - WINDFOR publish times: 2025-12-28T00:00 to 2026-02-01T00:00 London.
  - FUELHH settlement dates: 2026-01-01 to 2026-02-02, then filtered by
    `startTime` to the delivery window (2 Jan to 1 Feb London).

## Processed data (`data/processed/`)

Built from the repository root with
`python -m backend.app.fetch_data --decision-month 2026-01`. Timestamps are
stored as UTC ISO strings ending in `Z`; missing values are empty.

- `actuals.csv`: `start_time, generation_mw, publish_time, settlement_date,
  settlement_period`. All 1,488 half-hours from 2 Jan to 1 Feb 2026 are
  present.
- `forecasts.csv`: `publish_time, start_time, generation_mw`. 256 publications
  (the earliest is 31 Dec 2025 02:30 UTC) with at least one hour in the
  delivery window; 17,864 rows; no missing values.
- `manifest.json`: source URLs, every request (URL, parameters, retrieval
  time, attempts, SHA-256 of the raw body), row counts, cleaning counts, conflict
  examples, actual and forecast coverage, assumptions, and output fingerprints.

## Licence and redistribution

- Elexon's "Licence to use BMRS open data" (as summarised by Elexon) grants a
  worldwide, royalty-free, perpetual, non-exclusive licence to copy, adapt and
  commercially exploit BMRS data. Conditions: the attribution
  **"Contains BMRS data © Elexon Limited copyright and database right
  [year]"**, a link to the licence where possible, and no implied endorsement
  or misrepresentation.
- **Verification status:** the licence page sits behind a bot check that
  blocks automated access, so its full text was not read directly. The
  summary above comes from Elexon's page as shown in search results. Confirm
  the wording in a browser before publishing.
- The attribution is shown in the README, `data/README.md`, the manifest and
  the app footer.
- **Fallback if redistribution is unsuitable:** remove `data/processed/` from
  git and build with `DECISION_MONTH=2026-01` (a Docker build argument, or
  `heroku.yml` `config`). The data is then fetched once at image build time,
  never per request.

## Raw files in `data/raw/` (gitignored)

| File | Contents |
|---|---|
| `swagger.json` | OpenAPI spec |
| `docs_page_{FUELHH,WINDFOR}.rendered.html` and `.txt` | Rendered endpoint docs pages (the plain `.html` downloads are the empty JavaScript shell) |
| `page_wind-generation.html`, `page_generation-by-fuel-type.html` | Rendered Insights pages with the dataset descriptions quoted above |
| `sample_fuelhh.json`, `sample_windfor.json` | First small samples: 1 day of actuals, 12 h of forecast publications |
| `probe_*.json` | Range-limit, filter-combination, fuel-type and no-filter probes |
| `fuelhh_wind.json`, `windfor.json` | Earlier merged January downloads (from the first version of the script) |
| `2026-01/*.json` | Original response bodies from the pipeline, one file per request (fingerprints in the manifest) |
