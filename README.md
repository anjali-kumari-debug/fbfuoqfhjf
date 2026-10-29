# Wind Forecast Desk

A web app for a UK utility's day-ahead trading team. For every purchase decision
in January 2026 it shows:

1. **The latest wind generation forecast that was available at the decision
   cutoff.** It never uses a forecast published later.
2. **How accurate those forecasts were**, scored against actual generation:
   MAE, RMSE, bias and error percentiles, with data coverage.

Data: Elexon BMRS **WINDFOR** (wind forecasts, with every historical
publication) and **FUELHH** (actual generation, `fuelType = WIND`). No other
data is used.

**Live app:** _to be added after Vercel deployment_

---

## Key results (January 2026 decisions, 10:00 cutoff)

| Metric | Value |
|---|---|
| Coverage | 744 of 744 delivery hours scored (100%) |
| MAE | 2,013 MW |
| RMSE | 2,506 MW |
| Bias (mean error) | **+1,730 MW**: forecasts were consistently higher than actual output |
| Middle 80% of errors | -489 MW to +4,144 MW |

A later cutoff (16:00) reduces MAE to about 1,870 MW. With a cutoff before
02:30, the newest forecast doesn't yet cover the last 2 hours of the delivery
day, so coverage drops to 91.7%. The app reports this instead of filling in
those hours.

## How it works

| Rule | Implementation |
|---|---|
| Decision date | Every day from 1 to 31 Jan 2026 |
| Delivery day | The Europe/London calendar day after the decision date (2 Jan to 1 Feb) |
| Cutoff | Configurable in the UI. **10:00 London is a demo assumption, not a market rule.** |
| Forecast choice (no look-ahead) | For each delivery hour, the forecast with the latest `publishTime` at or before the cutoff. The selection function never receives actuals. |
| Resolution mismatch | Forecasts are hourly; actuals are half-hourly. Each hour's actual is the mean of its two half-hours. If either half-hour is missing, the hour is missing. Nothing is interpolated. |
| Missing data | Kept as `null` (shown as a gap or "—") and counted in coverage, per day and overall. Never filled with 0. |
| Error | `error = forecast - actual` (MW); positive = over-forecast. MAPE is not used because wind output can be near zero. |
| Timezones | All API timestamps are parsed as UTC and converted to Europe/London for day boundaries and display. Clock-change days (23 or 25 hours) are handled and tested. |

**Data scope caveat:** according to Elexon's documentation, both datasets cover
wind farms with operational metering on the transmission network. Embedded
wind is excluded, and metered wind is about 82% of GB wind according to NESO.
So these figures are **not total GB wind output**. See
[docs/data-notes.md](docs/data-notes.md) for the verified API details, data
limitations and comparability notes.

## Architecture

```
Elexon API ──(python -m backend.app.fetch_data, run once)──▶ data/raw/      (original responses, gitignored)
                                                             data/processed/ (normalised CSV + manifest)
                                                                   │
                                                                   ▼
Browser ◀── React (built static files) ◀── FastAPI ── app/analysis.py (selection, metrics)
                 └──────── /api/* JSON ────────┘
```

- **One service.** FastAPI serves both the JSON API (`/api/...`) and the built
  React app (`/`). The same app runs in one Docker image locally and as one
  Vercel Function in production (the React build is served from Vercel's CDN).
- **Offline data preparation.** One command fetches, preserves, validates and
  documents the data. The app reads only `data/processed/` and **never calls
  Elexon at request time**, so the demo is reproducible.
- **Pure core logic.** `backend/app/analysis.py` contains no web code, which
  makes the forecast-selection and metric rules easy to test.

### API

All dates are **decision dates**. Times are Europe/London. `decision_time`
defaults to `10:00`, a demo assumption rather than a market rule.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/forecast?decision_date=2026-01-10&decision_time=10:00` | Decision cutoff with its timezone offset (and in UTC), delivery date, and for each hourly interval: target time, selected forecast, its publish time, the retrospective actual, the error (only for matched intervals) and the lead time. Also coverage and that day's metrics. |
| `GET /api/accuracy?start_date=2026-01-01&end_date=2026-01-31&decision_time=10:00` | Pooled MAE, RMSE, bias and percentiles over all matched intervals; a daily table with each date's own cutoff, metrics and coverage; expected / forecast / actual / matched interval counts; the error sign definition; the decision-time assumption; an error histogram. `start_date` and `end_date` default to the whole of January. |
| `GET /api/meta` | Decision-date range, default decision time and its label, method notes, data retrieval date, attribution |

- **Coverage counts are reported separately:** `expected_intervals`,
  `forecast_intervals`, `actual_intervals` and `matched_intervals`. Metrics use
  matched intervals only, and are `null` when there are none.
- **Bad input gets HTTP 422 with a specific message:** dates outside
  January 2026, malformed dates, invalid times (for example `25:00` or `9:00`),
  `start_date` after `end_date`, and a missing `decision_date`.
- **Data loading:** the processed data is loaded **once at startup**. If a
  required file is missing, startup stops with instructions to run the data
  pipeline. No request ever calls Elexon.
- Routes (`app/main.py`) only validate input and shape JSON. Selection,
  alignment and metrics live in `app/analysis.py`.
- Interactive API docs are at `/docs`.

## Running it

Prerequisites: Python 3.13, Node.js 22+, Docker (optional).

### Option A: Docker (one image with the UI and API)

From the project root:

```bash
docker build -t wind-forecast-desk .
docker run --rm -p 8090:8000 wind-forecast-desk
```

Open http://localhost:8090. The container listens on `$PORT` (default 8000),
as most container platforms expect.

### Option B: local development (two terminals)

From the project root, set up once:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci)
```

Terminal 1, the backend (from `backend/`):

```bash
../.venv/bin/uvicorn app.main:app --reload --port 8001
```

Terminal 2, the frontend (from `frontend/`):

```bash
npm run dev
```

Open http://localhost:5180. The Vite dev server forwards `/api` to port 8001;
set `API_PORT` to use a different backend port. Ports 5180 and 8001 were chosen
to avoid the common defaults 5173 and 8000.

### Tests and checks

| What | Where to run | Command |
|---|---|---|
| Backend tests (117: selection, cutoff boundary, missing data, timezones, metrics, API endpoints and validation, cleaning, retries, pipeline) | `backend/` | `../.venv/bin/python -m pytest` |
| Frontend tests (7: London-time display and day labels, missing values, formatting) | `frontend/` | `npm test` |
| Frontend lint | `frontend/` | `npm run lint` |
| Production build | `frontend/` | `npm run build` |
| Tests inside the Docker image | anywhere | `docker run --rm wind-forecast-desk python -m pytest -q -p no:cacheprovider` |

## Data preparation pipeline

From the repository root (with the virtual environment active, or using
`.venv/bin/python`):

```bash
python -m backend.app.fetch_data --decision-month 2026-01
```

| Step | Behaviour |
|---|---|
| Date ranges | Worked out from the month. Delivery days are 2 Jan to 1 Feb. Forecast publications are fetched from 28 Dec, 4 days before the first decision (`--lookback-days`), to the end of 31 Jan. Actuals cover settlement dates 1 Jan to 2 Feb. |
| Requests | 7-day chunks, a 60 s timeout, and up to 4 attempts on timeouts, connection errors, 429 and 5xx, with waits that double each time (capped). Client errors such as 400 fail immediately. |
| Raw preservation | Each response body is saved unchanged to `data/raw/<month>/` (gitignored), with its SHA-256 in the manifest. |
| Normalisation | FUELHH is filtered to `WIND`. Timestamps are timezone-aware and written as UTC `...Z`. Older publications are kept, because filtering is on the target hour, not the publish time. |
| Validation | Unparseable timestamps, or timestamps off the 30-minute / hourly grid, are removed and counted. Non-numeric and non-finite MW values become missing and are counted; negative values are flagged. Settlement date and period are checked against `startTime`. |
| Duplicates | Exact duplicates are removed. **Conflicting duplicates are reported in the manifest.** A conflicting actual is resolved only by a later revision (a later `publishTime`); otherwise the value is set to missing, never picked arbitrarily. |
| Missing data | Preserved as empty values; nothing is filled or interpolated. |
| Outputs | `data/processed/actuals.csv`, `forecasts.csv` and `manifest.json`. The manifest records the source URLs, every request with its range and retrieval time, row counts, cleaning counts, actual and forecast coverage, the assumptions, and file fingerprints. |

For January 2026: 10 requests; 1,584 → 1,488 actual rows; 20,440 → 17,864
forecast rows from 256 publications. There were no duplicates, conflicts or
invalid values, and 100% actual and forecast coverage.

## Data licence and attribution

Contains BMRS data © Elexon Limited copyright and database right 2026.
[Licence](https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/).
This project is not endorsed by Elexon.

The processed January 2026 data (about 1 MB) is committed so that the demo and
tests are reproducible. Elexon's BMRS open-data licence, as summarised by
Elexon, allows copying, adaptation and commercial re-use **with this
attribution**. The attribution appears here, in `data/README.md`, in the
manifest and in the app footer.

If redistribution were not suitable, nothing else changes: delete
`data/processed/` from the repository and build the image with
`DECISION_MONTH`. The data is then fetched once at build time (see Deployment).

## Deployment (Vercel)

Vercel runs the FastAPI app as a Python function and serves the built React app
from its CDN. Docker is not used on Vercel; it remains the way to run the
production setup locally.

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.vercel] entrypoint = "backend.app.main:app"`, plus the runtime dependencies only |
| `.python-version` | Python 3.13 |
| `vercel.json` | Build command (`cd frontend && npm ci && npm run build`), and keeps `node_modules`, tests, raw data and docs out of the function bundle |
| `.vercelignore` | Keeps local-only and private files (virtual env, raw data, challenge document) from being uploaded |

The processed data in `data/processed/` is included in the function and loaded
once at startup. No request calls Elexon.

From the project root (after `npx vercel login`):

```bash
npx vercel deploy --prod
```

If redistributing the processed data were not allowed, remove
`data/processed/` from the repository and make the build command run the
pipeline first, adding `httpx` to `pyproject.toml`:
`python -m backend.app.fetch_data --decision-month 2026-01 && cd frontend && npm ci && npm run build`.

## Files and directories

| Path | Purpose |
|---|---|
| `README.md` | This file |
| `CLAUDE.md` | Project rules and conventions used while building (data rules, stack, workflow) |
| `Dockerfile` | Multi-stage build: Node builds the React app, then a Python image serves it with FastAPI (optional build-time data fetch with `DECISION_MONTH`) |
| `.dockerignore` | Keeps local-only files (virtual env, `node_modules`, raw data, secrets) out of the image |
| `pyproject.toml` | Vercel entrypoint and runtime dependencies |
| `.python-version` | Python version for Vercel (3.13) |
| `vercel.json` | Vercel build command and function bundle exclusions |
| `.vercelignore` | Files never uploaded to Vercel |
| `.gitignore` | Excludes virtual envs, `node_modules`, caches, `.env` files, `frontend/dist`, `data/raw` and the private challenge document |
| **backend/** | |
| `backend/requirements.txt` | Pinned Python dependencies |
| `backend/pytest.ini` | pytest configuration |
| `backend/app/main.py` | FastAPI routes: input validation, loading the data once at startup, JSON endpoints, serving the built frontend |
| `backend/app/serialize.py` | Converts pandas/numpy values to JSON-safe values (NaN becomes `null`, timestamps become UTC strings) |
| `backend/app/analysis.py` | Core logic: delivery-day hours, forecast selection at the cutoff, hourly alignment, coverage, metrics |
| `backend/app/elexon.py` | Elexon API client (bounded chunks, timeouts, bounded retries) and cleaning (WIND filter, UTC parsing, validation, duplicate and conflict handling) |
| `backend/app/fetch_data.py` | Data pipeline CLI (`python -m backend.app.fetch_data --decision-month 2026-01`): plans ranges, fetches, preserves raw, cleans, writes processed CSVs and the manifest |
| `backend/tests/test_analysis.py` | Tests for selection, cutoff boundary, missing data, timezones and clock changes, 31 Jan → 1 Feb, metrics, plus checks on the real processed data |
| `backend/tests/test_api.py` | Endpoint tests: required fields, cutoff with timezone, separate coverage counts, pooled vs daily metrics, null metrics, 422 validation, loading once at startup, clear failure when data is missing, static frontend |
| `backend/tests/test_elexon_clean.py` | Cleaning tests: WIND filter, exact duplicates vs conflicts, validation, grid checks, older publications kept, missing values |
| `backend/tests/test_fetch_data.py` | Pipeline tests against a fake API: date planning, retries and their limits, raw files preserved byte for byte, chunk sizes, manifest, coverage without filling gaps |
| **frontend/** | |
| `frontend/package.json`, `package-lock.json` | Node dependencies (React, Recharts, Vite) and scripts |
| `frontend/vite.config.js` | Vite config: dev port 5180, `/api` proxy to the backend |
| `frontend/index.html` | HTML entry page |
| `frontend/src/main.jsx` | React entry point |
| `frontend/src/App.jsx` | Page layout: tabs, cutoff control with its demo-assumption label, method notes |
| `frontend/src/components/DecisionView.jsx` | Decision view: what was known at the cutoff. January date picker, derived delivery date, forecast-only chart (tooltips show the publish time), coverage, which publication was used, partial and empty states |
| `frontend/src/components/AccuracyView.jsx` | Accuracy view: decision-date range selector, MAE / RMSE / bias / middle-80% / matched-interval cards with explanations, the retrospective actual-vs-forecast chart, a daily bias chart and table, partial and empty states |
| `frontend/src/components/StatTile.jsx`, `ChartTooltip.jsx`, `Notice.jsx` | Shared UI pieces: number cards (with an optional coverage meter), chart tooltips, status messages for partial, empty and error states |
| `frontend/src/api.js`, `useApi.js` | API URLs and a fetch hook that cancels outdated requests |
| `frontend/src/format.js` | London-time, MW and percentage formatting ("—" for missing values) |
| `frontend/src/format.test.js` | Tests for `format.js` |
| `frontend/src/theme.js` | Chart colours for light and dark mode, checked for colour-blind separation |
| `frontend/src/App.css`, `index.css` | Styles |
| `frontend/public/favicon.svg` | Browser tab icon |
| `frontend/.oxlintrc.json` | Lint rules |
| **data/** | |
| `data/README.md` | Data folders, how to recreate them, source attribution |
| `data/processed/actuals.csv` | Half-hourly WIND actuals, 2 Jan to 1 Feb 2026 London (1,488 rows) |
| `data/processed/forecasts.csv` | Every WINDFOR publication covering those days (256 publications, 17,864 rows) |
| `data/processed/manifest.json` | Sources, request ranges, retrieval times, row counts, cleaning and coverage report, assumptions |
| `data/raw/` | Original API responses and documentation captures (local only, gitignored) |
| **docs/** | |
| `docs/data-notes.md` | Verified Elexon endpoint details, field meanings, limitations, publish vs target time, dataset comparability |
| `docs/CHECKLIST.md` | Stage-by-stage implementation checklist |
| `docs/demo-script.md` | Outline for the demo video |

## Out of scope

No login, no data sources other than Elexon, no machine-learning forecasting,
and no recommendation of how much power to buy. The app reports forecasts and
their errors only.

## AI assistance

This project was built with substantial help from **Claude (Anthropic), using
Claude Code**. Claude helped with:

- planning the stages;
- inspecting the Elexon API documentation and responses;
- writing the backend, frontend, tests, Docker and Vercel configuration, and
  documentation.

All work was directed, reviewed and run step by step by the author. The data
rules (no look-ahead, missing data preserved, timezone handling) are enforced
by automated tests rather than taken on trust.
