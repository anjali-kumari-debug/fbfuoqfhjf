# CLAUDE.md

Guidance for Claude (and humans) working in this repository.
Full challenge text: `docs/requirements.md` (local only, gitignored).

## Product in one sentence

A web app for a UK utility's day-ahead trading team that shows (1) the latest
national WIND generation forecast available at their purchase-decision cutoff and
(2) how accurate those forecasts were against actual generation.

## Fixed stack

- Frontend: React + Vite + JavaScript, charts with Recharts.
- Backend: Python, FastAPI, pandas, httpx; tests with pytest.
- Packaging: one Docker image. FastAPI serves the built React app (`frontend/dist`)
  and the JSON API from the same service.
- Deployment: Heroku (container).
- Repo: public GitHub repo with a random, anonymous name.

## Out of scope

No login, no data sources other than Elexon, no ML forecasting, and no claims
about how much power to buy. We report forecasts and their errors only.

## Data sources (Elexon BMRS / Insights API)

- **Actuals:** `FUELHH` stream, rows with `fuelType == "WIND"` only.
  Fields: `startTime` (30-minute resolution), `generation` (MW).
- **Forecasts:** `WINDFOR` stream, which keeps historical publications.
  Fields: `startTime`, `publishTime` (when the forecast was made), `generation` (MW).
- Endpoints, parameters and resolutions are verified in `docs/data-notes.md`.
- **Alignment (decided):** WINDFOR is hourly and FUELHH is half-hourly. Score
  on the hourly grid: forecast for hour `T` vs the mean of the actual
  half-hours starting at `T` and `T+30min`. If either half-hour is missing,
  the hour's actual is missing. Never interpolate. State this in UI and README.

## Data rules (must hold everywhere)

1. **Decision dates:** every calendar day in January 2026 (1 to 31 Jan).
2. **Delivery day** = the Europe/London calendar day after the decision date.
   Delivery days are therefore 2 Jan to 1 Feb 2026.
3. **Cutoff time** is configurable. `10:00` Europe/London is the default, and the
   UI must label it as a *demo assumption*, not a market rule.
4. **Forecast selection (no look-ahead):** for each delivery interval, use the
   forecast with the latest `publishTime` that is `<=` the decision cutoff
   (decision date + cutoff time, Europe/London). Never use a forecast published
   after the cutoff.
   - Fetch forecasts with publish times starting a few days before 1 Jan 2026,
     so early-January decisions can use late-December forecasts.
5. **Missing data is preserved.** If an interval has no eligible forecast or no
   actual, keep it as missing (null/NaN). Never fill with 0 and never drop it
   silently. Report **coverage** (intervals with data / expected intervals)
   per day and overall.
6. **Actuals are evaluation-only.** They are retrospective and are used only to
   score forecasts, never to choose or adjust them.
7. **Include 1 Feb 2026 actuals** so that 31 Jan decisions can be evaluated.
8. **Timezones:** parse every timestamp as timezone-aware (API values are UTC).
   Convert to Europe/London for day boundaries and display. Never use naive
   datetimes. January has no clock change, but the code must not depend on that.
9. **Error convention:** `error = forecast - actual` (MW). Positive means
   over-forecast. Metrics: MAE, RMSE, mean error (bias), and error percentiles.
   Avoid MAPE because wind generation can be close to zero.

## Reproducibility

- Raw API downloads go in `data/raw/` (gitignored).
- A small, cleaned historical snapshot is committed in `data/snapshot/`,
  so the demo and tests run without calling Elexon.
- A script re-creates the snapshot from the API.

## Layout

```
backend/     FastAPI app (app/), snapshot script (scripts/), pytest tests (tests/)
frontend/    React + Vite app; npm test runs node:test (build output dist/ is gitignored)
data/        raw/ (ignored) and snapshot/ (committed)
docs/        checklist, data notes, demo script (requirements.md is local only)
Dockerfile   multi-stage: build frontend, then run FastAPI
heroku.yml   Heroku builds the Dockerfile on its own servers
```

Dev ports: frontend 5180, backend 8001 (other local projects use 5173/8000).

## Deliverables

- README: what each file and directory is for, how to start the app locally and
  with Docker, the deployed Heroku URL, and an explicit statement of
  Claude/AI assistance.
- Demo video of 10 minutes or less: about 5 minutes client pitch plus about
  5 minutes technical walkthrough.
- Total time budget: 16 hours.

## How to work in this repo

- The user is a beginner. Explain the purpose of each step in plain language.
- Make small, coherent changes, one stage at a time (see `docs/CHECKLIST.md`).
- Always state which directory each command must be run from.
  Run commands from the project root (the folder containing this file) unless
  stated otherwise. Quote paths, because some local files contain spaces.
- Run the relevant checks (tests, build, lint) after each change and explain
  any failure.
- Stop at the end of each stage and wait for the user.
- **Never commit or push unless the user explicitly asks.**
- Never commit secrets. Only a secret-free `.env.example` may be committed.
