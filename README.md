# Wind Forecast Desk

**Live app:** https://fbfuoqfhjf.vercel.app  
**Repository:** https://github.com/anjali-kumari-debug/fbfuoqfhjf  
**Demo video:** _to be added (unlisted YouTube link)_

> **Status: pilot / demo.** This is a first version built for a recruitment
> challenge. It is not production-ready. It has no authentication, monitoring
> or alerting, it uses a fixed January 2026 data snapshot, and the decision
> time is an assumption, not a verified market rule.

## 1. Business problem

A UK electricity supplier's day-ahead trading team must buy power one day
before delivery. Wind output is weather-dependent, so they rely on wind
generation forecasts to judge how much other generation they need. Two
questions matter at decision time:

1. **What was the latest wind forecast available when the decision had to be
   made?** Only forecasts published at or before the decision time count.
2. **How accurate have those forecasts been?** The team can then decide with
   the size and direction of the typical error in mind.

This app answers both questions for every decision date in January 2026, using
national wind data from Elexon only.

**Not provided:** demand data, purchase recommendations or procurement volumes.
The app reports forecasts and their errors; it is **not** a calculator for how
much power to buy.

## 2. Results at a glance (January 2026 decisions, 10:00 decision time)

| Measure | Value |
|---|---|
| Coverage | 744 of 744 delivery hours matched (100%) |
| MAE | 2,013 MW |
| RMSE | 2,506 MW |
| Bias (mean error) | **+1,730 MW**: forecasts were higher than actual output in most hours |
| Middle 80% of errors | −489 MW to +4,144 MW |
| Skill vs a naive persistence baseline | about 53% lower MAE (on the 720 hours where the baseline exists) |

More detail, with breakdowns and interpretation, is in
[docs/evaluation.md](docs/evaluation.md). These figures describe one winter
month (see Known limitations).

## 3. Scope and decision rules

| Rule | Implementation |
|---|---|
| Decision dates | Every calendar day from **1 to 31 January 2026** |
| Delivery day | The **next Europe/London calendar day** after the decision date. Delivery days therefore run from 2 January to **1 February 2026**. Actuals for 1 February are included so that 31 January decisions can be scored. |
| Decision time (cutoff) | **Configurable** in the UI and API (`decision_time`, HH:MM, Europe/London). The default **10:00 is a demo assumption, not a verified market rule.** |
| Forecast selection | For each delivery hour, the forecast with the **latest `publishTime` at or before the decision cutoff**. A forecast published even one minute later is never used. Publications from before January (from 28 December 2025) are kept, so early-January decisions can use late-December forecasts. The selection code never receives actuals. |
| Month-wide analysis | Each decision date uses **its own cutoff** and its own next-day delivery hours (not one month-end cutoff). |
| Resolution mismatch | Forecasts are hourly; actuals are half-hourly. Each hour's actual is the **mean of its two half-hours**. If either half-hour is missing, the hour is missing. Nothing is interpolated. |
| Missing data | Kept as `null` (shown as a gap or "—"), never replaced with 0, and reported as coverage |
| Timezones | All API timestamps are parsed as timezone-aware UTC and converted to Europe/London for day boundaries and display. Clock-change days (23 or 25 hours) are handled and tested, although January has none. |

Example: with a decision time before 02:30, the newest available forecast does
not yet cover the last 2 hours of the delivery day. Coverage then drops to
22 of 24 hours, and the app shows those hours as missing.

## 4. Metric definitions

`error = forecast − actual` (MW). **Positive means over-forecast.**

Metrics use **matched intervals only** (hours with both a selected forecast
and an actual). With no matched intervals, every metric is `null`, not 0.

| Metric | Definition |
|---|---|
| MAE | mean(\|error\|): the typical size of a miss |
| RMSE | √mean(error²): penalises large misses more |
| Bias | mean(error): a systematic lean (positive = forecast too high) |
| Percentiles | P10 to P90 of the errors; also the P90 of \|error\| ("9 in 10 hours missed by less") |
| Skill vs baseline | 1 − MAE(forecast) ÷ MAE(persistence), on the same hours. The persistence baseline is the latest actual *published* by the cutoff, assumed to continue all day. |
| Coverage | Four counts reported separately: **expected** intervals (hours in the delivery day), intervals with a **selected forecast**, intervals with an **actual**, and **matched** intervals (both). Ratios are count ÷ expected. |

MAPE is not used, because wind output can be close to zero.

## 5. Architecture

```
Elexon API ──(python -m backend.app.fetch_data, run once)──▶ data/raw/        original responses (gitignored)
                                                             data/processed/  normalised CSVs + manifest (committed)
                                                                   │  loaded once at startup
                                                                   ▼
Browser ◀── React build (static files) ◀── FastAPI ── backend/app/analysis.py (selection, alignment, metrics)
                 └──────────── /api/* JSON ─────────────┘
```

- **One service.** FastAPI serves the JSON API (`/api/...`) and the built React
  app (`/`). It runs as one Docker image locally, and as one Vercel Python
  function in deployment (Vercel serves the React files from its CDN).
- **No calls to Elexon at request time.** The app reads only
  `data/processed/`, loaded once at startup. If those files are missing,
  startup fails with instructions to run the data pipeline.
- **Logic kept separate from web code.** `backend/app/analysis.py` (selection,
  alignment, metrics) has no web code; `backend/app/main.py` only validates
  input and shapes JSON.

### API

All dates are **decision dates**; times are Europe/London; `decision_time`
defaults to `10:00`. Interactive docs are at `/docs`.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/forecast?decision_date=2026-01-10&decision_time=10:00` | The cutoff (with timezone offset, and in UTC) and the delivery date. For each hour: target time, selected forecast, its publish time, the retrospective actual, and the error (only for matched hours). Also coverage, that day's metrics, and the forecast's recent error record over the previous 7 decisions (using only actuals published by the cutoff). |
| `GET /api/accuracy?start_date=2026-01-01&end_date=2026-01-31&decision_time=10:00` | Pooled metrics and coverage; a daily table (each date with its own cutoff); the hourly forecast-vs-actual series; skill vs the persistence baseline; breakdowns by time of day and actual wind level; an error histogram; the error-sign definition and the decision-time assumption |
| `GET /api/accuracy/decision-times?start_date=&end_date=` | The same decision dates scored at 00:00, 02:30, 06:00, 10:00, 12:30, 16:00 and 20:00 |
| `GET /api/meta` | Date range, default decision time and its label, method notes, data retrieval date, attribution |

Invalid input gets HTTP 422 with a specific message. Examples: dates outside
January 2026, malformed dates, times such as `25:00` or `9:00`, and
`start_date` after `end_date`.

## 6. Prerequisites

- **Python 3.13** (for the backend and the data pipeline)
- **Node.js 20.19+ or 22.12+, with npm** (Vite's requirement; the frontend build)
- **Docker** (optional; for Option A)
- A Unix-like shell (macOS or Linux). The commands below use `.venv/bin/...` paths.

## 7. Running it

### Option A: Docker

From the repository root:

```bash
docker build -t wind-forecast-desk .
docker run --rm -p 8090:8000 wind-forecast-desk
```

Open http://localhost:8090. The container listens on `$PORT` (default 8000).

### Option B: local backend and frontend (two terminals)

One-time setup, from the repository root:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && cd ..
```

Terminal 1, the backend, from `backend/`:

```bash
cd backend
../.venv/bin/uvicorn app.main:app --reload --port 8001
```

Terminal 2, the frontend, from `frontend/`:

```bash
cd frontend
npm run dev
```

Open http://localhost:5180. The Vite dev server forwards `/api` to port 8001
(set `API_PORT` to use another). Ports 5180 and 8001 avoid the common defaults
5173 and 8000.

Every view has a shareable URL, for example
`/?view=accuracy&time=16:00&start=2026-01-10&end=2026-01-20`. Use the **Copy
link to this view** button.

## 8. Tests

| What | Run from | Command |
|---|---|---|
| Backend tests (139) | `backend/` | `../.venv/bin/python -m pytest` |
| Frontend tests (11) | `frontend/` | `npm test` |
| Frontend lint | `frontend/` | `npm run lint` |
| Frontend build | `frontend/` | `npm run build` |
| Backend tests inside the Docker image | anywhere, after `docker build` | `docker run --rm wind-forecast-desk python -m pytest -q -p no:cacheprovider` |

**Backend tests cover:**
- forecast selection, including the exact cutoff boundary (a forecast at
  10:00 is used, at 10:01 it is not), a later ineligible forecast, and
  multiple eligible forecasts;
- missing forecasts and actuals, real zero generation, and no matched
  intervals;
- the 31 January → 1 February delivery boundary, and clock-change days;
- duplicates and conflicting rows;
- MAE, RMSE and bias, against hand-calculated examples;
- the API endpoints and input validation;
- data cleaning, API retries, and the pipeline (against a fake API);
- the evaluation metrics.

**Frontend tests cover** formatting (London time, missing values shown as "—")
and shareable-link parsing. There are no automated browser/UI tests.

The pytest run prints one known, harmless warning: a deprecation notice from
Starlette's test client about `httpx`.

## 9. Data: sources, attribution and reproduction

### Source datasets (Elexon Insights Solution / BMRS)

| Dataset | API endpoint used | Documentation |
|---|---|---|
| Actual generation, `fuelType = WIND` (FUELHH) | `https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH/stream` | https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream |
| Wind generation forecast (WINDFOR) | `https://data.elexon.co.uk/bmrs/api/v1/datasets/WINDFOR/stream` | https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream |

Verified endpoint details, field meanings and data observations are in
[docs/data-notes.md](docs/data-notes.md).

**Attribution:** Contains BMRS data © Elexon Limited copyright and database
right 2026. Licence:
https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/.
This project is not endorsed by Elexon.

The processed January data (about 1 MB) is committed so that the demo and tests
are reproducible. Elexon's BMRS open-data licence is understood to allow reuse
with this attribution. Its full text could not be retrieved automatically, so
the wording should be confirmed on the licence page above.

### Reproducing the data snapshot

From the repository root:

```bash
.venv/bin/python -m backend.app.fetch_data --decision-month 2026-01
```

What the command does:

- **Requests:**
  - WINDFOR publications from 28 December 2025 to the end of 31 January, and
    FUELHH WIND actuals for settlement dates 1 January to 2 February;
  - 7-day chunks, a 60-second timeout, and up to 4 attempts on timeouts,
    429 and 5xx errors.
- **Raw files:** every original response is saved unchanged in
  `data/raw/2026-01/` (gitignored), with its SHA-256 in the manifest.
- **Cleaning:**
  - FUELHH is filtered to `WIND`, and all times are stored as UTC;
  - exact duplicates are removed; conflicting duplicates are reported, never
    picked arbitrarily;
  - invalid values become missing and are counted.
- **Outputs:** `data/processed/actuals.csv`, `forecasts.csv` and
  `manifest.json` (sources, request ranges, retrieval times, row counts,
  cleaning counts, coverage, assumptions).

For January 2026 the pipeline made 10 requests:

- **Actuals:** 1,584 rows → 1,488.
- **Forecasts:** 20,440 rows → 17,864, from 256 publications.
- **Quality:** no duplicates, conflicts or invalid values; 100% actual
  coverage.

## 10. Deployment (Vercel)

The live app runs on Vercel. Vercel does not use the Dockerfile; it runs the
FastAPI app as a Python function and serves the React build from its CDN.

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.vercel] entrypoint = "backend.app.main:app"` and the runtime dependencies |
| `.python-version` | Python 3.13 |
| `vercel.json` | Build command (`cd frontend && npm ci && npm run build`) and files kept out of the function bundle |
| `.vercelignore` | Keeps local-only and private files from being uploaded |

The Vercel project is connected to the GitHub repository; pushes to `main`
redeploy it. Manual deploy, from the repository root after `npx vercel login`:
`npx vercel deploy --prod`.

## 11. Performance

No performance benchmarks are recorded in this repository.

## 12. Known limitations

- **One month, one season.** Results cover January 2026 only (744 delivery
  hours). Days are not independent, so treat percentages as indicative.
- **Not total GB wind.** Per Elexon's documentation, both datasets cover wind
  farms with operational metering on the transmission network. Embedded wind
  is excluded; NESO estimates metered wind at about 82% of GB wind.
- **Comparability assumptions:**
  - The hourly actual is the mean of two half-hours. It is not verified
    whether a WINDFOR value represents an hourly average or the value at the
    start of the hour.
  - Elexon's documented publication times differ from the observed
    `publishTime` values by one hour; the app uses the observed values.
- **Cause of the bias is unknown.** The forecasts ran about 1.7 GW high on
  average. Possible causes, such as curtailment or scope differences, are not
  verified.
- **Decision time is an assumption.** 10:00 Europe/London is a demo default,
  not a verified market cutoff; the market timetable is not modelled.
- **No demand data.** The app cannot and does not suggest purchase volumes.
- **Fixed snapshot.** The app does not update itself. New data needs a pipeline
  run and a redeploy.
- **Pilot quality.** No authentication, monitoring or automated browser tests.

## 13. Repository contents

| Path | Purpose |
|---|---|
| `README.md` | This file |
| `CLAUDE.md` | Project rules used while building (data rules, stack, workflow) |
| `Dockerfile` | Multi-stage build: Node builds the React app; Python serves it and the API with FastAPI. Optional build-time data fetch with `DECISION_MONTH`. |
| `.dockerignore` | Keeps local-only files (virtual env, `node_modules`, raw data, secrets) out of the image |
| `pyproject.toml`, `.python-version`, `vercel.json`, `.vercelignore` | Vercel deployment configuration (see section 10) |
| `.gitignore` | Excludes virtual envs, `node_modules`, caches, `.env` files, `frontend/dist`, `data/raw`, `.vercel` and the private challenge document |
| **backend/** | |
| `backend/requirements.txt` | Pinned Python dependencies (development and Docker) |
| `backend/pytest.ini` | pytest configuration |
| `backend/app/__init__.py` | Marks `app` as a Python package |
| `backend/app/main.py` | FastAPI routes: input validation, loading data once at startup, JSON responses, serving the built frontend |
| `backend/app/analysis.py` | Core logic: delivery-day hours, forecast selection at the cutoff, hourly alignment, coverage, metrics, recent error record, persistence baseline, breakdowns |
| `backend/app/serialize.py` | Converts pandas/numpy values to JSON-safe values (NaN becomes `null`, timestamps become UTC strings) |
| `backend/app/elexon.py` | Elexon API client (bounded chunks, timeouts, bounded retries) and cleaning |
| `backend/app/fetch_data.py` | Data pipeline command (section 9) |
| `backend/app/evaluate.py` | Evaluation command, `python -m backend.app.evaluate`: extended metrics, baseline skill, breakdowns, a no-look-ahead bias what-if (analysis only, not used by the app) |
| `backend/tests/test_analysis.py` | Selection, cutoff boundary, missing data, zero generation, timezones, 31 Jan → 1 Feb, duplicates, metrics, recent error record, baseline, breakdowns |
| `backend/tests/test_api.py` | Endpoints, validation (422), null metrics, loading once at startup, failure when data is missing |
| `backend/tests/test_elexon_clean.py` | Cleaning: WIND filter, duplicates vs conflicts, validation, older publications kept |
| `backend/tests/test_fetch_data.py` | Pipeline against a fake API: date planning, retries, raw files preserved byte for byte, manifest, coverage |
| `backend/tests/test_evaluate.py` | Evaluation metrics, skill score, baseline and correction without look-ahead |
| **frontend/** | |
| `frontend/README.md` | Frontend commands |
| `frontend/package.json`, `package-lock.json` | Node dependencies (React, Recharts, Vite) and scripts |
| `frontend/vite.config.js` | Dev server on port 5180, with an `/api` proxy to the backend |
| `frontend/.gitignore`, `frontend/.oxlintrc.json` | Frontend ignore rules and lint rules |
| `frontend/index.html`, `frontend/public/favicon.svg` | HTML entry page and tab icon |
| `frontend/src/main.jsx`, `App.jsx` | React entry point; page layout, tabs, decision-time control, method notes, shareable-link state |
| `frontend/src/components/DecisionView.jsx` | Decision view: what was known at the cutoff. Forecast chart with publish times, recent error cards and range band, coverage, which publication was used. |
| `frontend/src/components/AccuracyView.jsx` | Accuracy view: date range, metric cards with explanations, actual-vs-forecast chart, daily bias, skill card, breakdowns, decision-time comparison |
| `frontend/src/components/StatTile.jsx`, `ChartTooltip.jsx`, `Notice.jsx` | Shared UI pieces (cards, tooltips, status messages for loading, partial, empty and error states) |
| `frontend/src/api.js`, `useApi.js` | API URLs; a fetch hook that cancels outdated requests |
| `frontend/src/format.js`, `format.test.js` | London-time and MW formatting ("—" for missing values), with tests |
| `frontend/src/urlState.js`, `urlState.test.js` | Shareable-link state, with tests |
| `frontend/src/theme.js`, `App.css`, `index.css` | Chart colours (light and dark) and styles |
| **data/** | |
| `data/README.md` | Data folders, reproduction command, attribution |
| `data/processed/actuals.csv` | Half-hourly WIND actuals, 2 January to 1 February 2026 (1,488 rows) |
| `data/processed/forecasts.csv` | Every WINDFOR publication covering those days (256 publications, 17,864 rows) |
| `data/processed/manifest.json` | Sources, request ranges, retrieval times, counts, coverage, assumptions |
| `data/raw/` | Original API responses (local only, gitignored) |
| **docs/** | |
| `docs/data-notes.md` | Verified Elexon endpoint details, publish vs target time, data limitations and comparability |
| `docs/evaluation.md` | Metric definitions, January results, interpretation, suggested improvements |
| `docs/CHECKLIST.md` | Stage-by-stage build checklist |
| `docs/demo-script.md` | Outline for the demo video |

## 14. AI assistance

This project was built with substantial help from **Claude (Anthropic), using
Claude Code**, an AI coding assistant.

**What Claude did:**
- **Planning:** proposed the stage plan.
- **Data research:** inspected the Elexon API documentation and real
  responses, and wrote `docs/data-notes.md`.
- **Writing:** the backend, frontend, data pipeline, tests, Docker and Vercel
  configuration, and documentation, including this README.
- **Checks:** ran the tests, lint and builds after changes; checked the UI in
  a headless browser; measured live responses; and ran an independent
  AI-assisted code review, whose bugs were fixed and covered by tests.

**What the author did:**
- **Requirements:** set the requirements and data rules.
- **Decisions:** made the design decisions, including:
  - averaging half-hours to compare with hourly forecasts;
  - deploying on Vercel as a single project;
  - which suggested improvements to build and which to drop.
- **Review:** reviewed the work stage by stage and requested further checks.
- **Running it:** ran the app locally and reported problems.
- **Publishing:** committed and pushed the code, and created and connected
  the GitHub and Vercel accounts.

The core data rules (no look-ahead, missing data preserved, timezone
handling) are enforced by automated tests rather than taken on trust.
