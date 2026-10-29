# Implementation checklist (16-hour budget)

Hour estimates are guides. Stop and review at the end of each stage.

- [x] **0. Setup (0.5h):** CLAUDE.md, .gitignore, this checklist.
- [x] **1. Explore data (1.5h):** check the FUELHH and WINDFOR stream endpoints,
      parameters, field formats and WINDFOR resolution. Save samples to `data/raw/`.
- [x] **2. Data pipeline (1.5h):** `python -m backend.app.fetch_data --decision-month 2026-01`.
      Bounded chunks and retries, raw responses preserved, validation, conflict
      reporting, coverage, manifest. Output in `data/processed/`.
- [x] **3. Core logic + tests (3h):** timezone-aware parsing, delivery-day
      intervals, latest forecast at or before the cutoff, coverage, and error
      metrics. pytest covers edge cases (cutoff boundary, missing data,
      31 Jan → 1 Feb).
- [x] **4. FastAPI endpoints (1.5h):** for example `/api/health`,
      `/api/decision?date=&cutoff=` and `/api/accuracy?cutoff=`, with tests.
- [x] **5. React UI (3h):** decision view (forecast vs actual chart, cutoff
      label, coverage) and accuracy view (MAE, RMSE, bias, error distribution).
- [x] **6. Docker (1h):** multi-stage build. FastAPI serves `frontend/dist`.
      Run locally.
- [ ] **7. Heroku deploy (1h):** container deploy, then check in incognito.
      Done: `heroku.yml` added; amd64 image rehearsed locally.
      To do: Heroku CLI + login, create app, push, check in incognito.
- [ ] **8. README + GitHub (1h):** directory guide, startup steps, URL,
      AI-assistance disclosure. Public repo with a random name.
      Done: README written (Heroku URL still to fill in).
      To do: `gh auth login`, create public repo `azoouh`, push.
- [ ] **9. Demo video (2h):** at most 10 minutes (about 5 minutes pitch and
      about 5 minutes technical). Upload as unlisted on YouTube and check in
      incognito. Script ready: `docs/demo-script.md`.
