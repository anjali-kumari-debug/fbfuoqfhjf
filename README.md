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

**Live app:** _to be added after Heroku deployment_

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
Elexon API ──(scripts/build_snapshot.py, run once)──▶ data/snapshot/*.csv  (committed)
                                                            │
                                                            ▼
Browser ◀── React (built static files) ◀── FastAPI ── app/analysis.py (selection, metrics)
                 └──────── /api/* JSON ────────┘
```

- **One service.** FastAPI serves both the JSON API (`/api/...`) and the built
  React app (`/`). One Docker image is deployed to Heroku.
- **Committed snapshot.** The app and tests run from `data/snapshot/` and never
  call Elexon at runtime, so the demo is reproducible. A script rebuilds the
  snapshot from the API.
- **Pure core logic.** `backend/app/analysis.py` contains no web code, which
  makes the forecast-selection and metric rules easy to test.

### API

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/meta` | Date range, default cutoff with its demo-assumption label, method notes, snapshot date |
| `GET /api/decision?date=2026-01-15&cutoff=10:00` | Per-hour forecast, publish time used, actual, error and lead time, plus coverage and metrics for that decision |
| `GET /api/accuracy?cutoff=10:00` | Per-day table, overall metrics and coverage, error histogram for all January decisions |

Invalid input (a date outside January, or a malformed cutoff) returns HTTP 422
with a clear message. Interactive API docs are at `/docs`.

## Running it

Prerequisites: Python 3.13, Node.js 22+, Docker (optional).

### Option A: Docker (closest to production)

From the project root:

```bash
docker build -t wind-forecast-desk .
docker run --rm -p 8090:8000 wind-forecast-desk
```

Open http://localhost:8090. The container listens on `$PORT` (default 8000),
as Heroku requires.

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
| Backend tests (61: selection, cutoff boundary, missing data, timezones, metrics, API) | `backend/` | `../.venv/bin/python -m pytest` |
| Frontend tests (6: London-time display, missing values, formatting) | `frontend/` | `npm test` |
| Frontend lint | `frontend/` | `npm run lint` |
| Production build | `frontend/` | `npm run build` |
| Tests inside the Docker image | anywhere | `docker run --rm wind-forecast-desk python -m pytest -q -p no:cacheprovider` |

### Rebuilding the data snapshot (optional)

From `backend/`:

```bash
../.venv/bin/python -m scripts.build_snapshot
```

This downloads WINDFOR publications (28 Dec 2025 to 31 Jan 2026) and FUELHH WIND
actuals (1 Jan to 2 Feb 2026) in 7-day chunks, cleans them, and rewrites
`data/snapshot/`. Raw downloads go to `data/raw/`, which is gitignored.

## Deployment (Heroku)

`heroku.yml` tells Heroku to build the `Dockerfile` on its own servers (amd64)
and run it as the `web` process.

```bash
heroku create <app-name>
heroku stack:set container
git push heroku main
```

## Files and directories

| Path | Purpose |
|---|---|
| `README.md` | This file |
| `CLAUDE.md` | Project rules and conventions used while building (data rules, stack, workflow) |
| `Dockerfile` | Multi-stage build: Node builds the React app, then a Python image serves it with FastAPI |
| `.dockerignore` | Keeps local-only files (virtual env, `node_modules`, raw data, secrets) out of the image |
| `heroku.yml` | Heroku container build configuration |
| `.gitignore` | Excludes virtual envs, `node_modules`, caches, `.env` files, `frontend/dist`, `data/raw` and the private challenge document |
| **backend/** | |
| `backend/requirements.txt` | Pinned Python dependencies |
| `backend/pytest.ini` | pytest configuration |
| `backend/app/main.py` | FastAPI app: input validation, JSON endpoints, serving the built frontend |
| `backend/app/analysis.py` | Core logic: delivery-day hours, forecast selection at the cutoff, hourly alignment, coverage, metrics |
| `backend/app/elexon.py` | Elexon API client (7-day chunks) and data cleaning (WIND only, UTC parsing, duplicates, counted removals) |
| `backend/scripts/build_snapshot.py` | Rebuilds `data/snapshot/` from the API and writes a quality report |
| `backend/tests/test_analysis.py` | Tests for selection, cutoff boundary, missing data, timezones and clock changes, 31 Jan → 1 Feb, metrics, plus checks on the real snapshot |
| `backend/tests/test_api.py` | API tests: responses, validation (422), `null` rather than NaN in JSON, static frontend serving |
| `backend/tests/test_elexon_clean.py` | Cleaning tests: WIND filter, duplicates, window edges, missing values and timestamps |
| **frontend/** | |
| `frontend/package.json`, `package-lock.json` | Node dependencies (React, Recharts, Vite) and scripts |
| `frontend/vite.config.js` | Vite config: dev port 5180, `/api` proxy to the backend |
| `frontend/index.html` | HTML entry page |
| `frontend/src/main.jsx` | React entry point |
| `frontend/src/App.jsx` | Page layout: tabs, cutoff control with its demo-assumption label, method notes |
| `frontend/src/components/DecisionView.jsx` | One decision: forecast at the cutoff, then the retrospective scoring, chart and hourly table |
| `frontend/src/components/AccuracyView.jsx` | January summary: metrics, daily MAE and bias charts, error histogram, daily table |
| `frontend/src/components/StatTile.jsx`, `ChartTooltip.jsx` | Small shared UI pieces |
| `frontend/src/api.js`, `useApi.js` | API URLs and a fetch hook that cancels outdated requests |
| `frontend/src/format.js` | London-time, MW and percentage formatting ("—" for missing values) |
| `frontend/src/format.test.js` | Tests for `format.js` |
| `frontend/src/theme.js` | Chart colours for light and dark mode, checked for colour-blind separation |
| `frontend/src/App.css`, `index.css` | Styles |
| `frontend/public/favicon.svg` | Browser tab icon |
| `frontend/.oxlintrc.json` | Lint rules |
| **data/** | |
| `data/snapshot/actuals.csv` | Half-hourly WIND actuals, 2 Jan to 1 Feb 2026 London (1,488 rows) |
| `data/snapshot/forecasts.csv` | Every WINDFOR publication covering those days (256 publications, 17,864 rows) |
| `data/snapshot/metadata.json` | Download ranges, row counts and data-quality report |
| `data/raw/` | Raw API downloads and documentation captures (local only, gitignored) |
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
- writing the backend, frontend, tests, Docker and Heroku configuration, and
  documentation.

All work was directed, reviewed and run step by step by the author. The data
rules (no look-ahead, missing data preserved, timezone handling) are enforced
by automated tests rather than taken on trust.
