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
      `/api/forecast?decision_date=&decision_time=` and
      `/api/accuracy?start_date=&end_date=&decision_time=`, with tests.
- [x] **5. React UI (3h):** decision view (forecast vs actual chart, cutoff
      label, coverage) and accuracy view (MAE, RMSE, bias, error distribution).
- [x] **6. Docker (1h):** multi-stage build. FastAPI serves `frontend/dist`.
      Run locally.
- [ ] **7. Vercel deploy (1h):** FastAPI function + React build on the CDN, then check in incognito.
      Done: `pyproject.toml`, `vercel.json`, `.vercelignore`, `.python-version`.
      To do: `npx vercel login`, `npx vercel deploy --prod`, check in incognito.
- [ ] **8. README + GitHub (1h):** directory guide, startup steps, URL,
      AI-assistance disclosure. Public repo with a random name.
      Done: README written (Vercel URL still to fill in).
      Done: public repo https://github.com/anjali-kumari-debug/fbfuoqfhjf pushed.
- [ ] **9. Demo video (2h):** at most 10 minutes (about 5 minutes pitch and
      about 5 minutes technical). Upload as unlisted on YouTube and check in
      incognito. Script ready: `docs/demo-script.md`.
