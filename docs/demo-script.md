# Demo video script (10 minutes or less)

Record as an **unlisted YouTube** video. Two parts of about 5 minutes each.
Use the **deployed Heroku app** for Part 1 (it proves the deployment works).
Timings are targets. Say the bullet points in your own words; don't read them.

Before recording:
- Open the app on the Decision view, with the 10:00 cutoff and decision date 15 Jan.
- Open a second tab on the Accuracy view.
- Open your editor on `backend/app/analysis.py`.
- Close notifications and other tabs, and zoom the browser to 110–125% so text
  is readable.

---

## Part 1: Client pitch (about 5 min)

**Audience:** the trading team. Talk about their decisions, not about code.

### 1. The problem (0:00–0:45)
- "Every day you buy tomorrow's power before you know how much wind there
  will be, so you rely on a forecast."
- "Two questions matter: *what did the forecast say when I had to decide?*
  and *how far can I trust it?* This pilot answers both for every decision
  you made in January 2026."

### 2. Decision view (0:45–2:15)
- Show decision **15 Jan at 10:00 → delivery 16 Jan**.
- Point to "Forecast published 15 Jan, 09:30": *"This is exactly what you
  could have seen at 10:00, nothing published later."*
- Point to the **cutoff box and its badge**: *"10:00 is our demo assumption,
  not a market rule. Set it to your real cutoff."*
- Hover the chart: forecast vs actual, hour by hour; the error is shown for
  each hour.
- Point out the two sections: **what you could see at the cutoff** vs **how it
  turned out**. *"Actuals are only used to score, never to choose."*
- Click **Next day** once or twice.

### 3. Accuracy over January (2:15–4:00)
- Headline numbers: **MAE about 2,000 MW; bias +1,730 MW.**
- *"The key finding: forecasts were consistently **too high**, by about 1.7
  GW on average. If you bought only to cover the gap left by the forecast
  wind, you would usually have been short."* Use the histogram: most bars are
  red (over-forecast).
- Daily charts: *"Some days are far worse"* (click **28 Jan**, the worst day,
  to open it). *"That's when the uncertainty matters most."*
- Change the cutoff to **16:00**: MAE drops to about 1,870 MW. *"Later
  forecasts are better. This quantifies what waiting buys you."*
- Change the cutoff to **01:00**: coverage drops to 91.7%. *"When the
  forecast didn't yet cover an hour, we tell you. We never fill it in."*

### 4. Honest limits and next steps (4:00–5:00)
- The data covers **metered transmission-connected wind farms (about 82% of
  GB wind)**, not embedded wind.
- We report errors; we don't tell you how much to buy.
- Possible next steps: other months, solar, error bands by time of day or
  forecast age, a live feed.

---

## Part 2: Technical walkthrough (about 5 min)

**Audience:** the tech lead reviewing the work. Show the code and the
reasoning.

### 1. Architecture (0:00–1:00)
- Show the README architecture diagram. One Docker image: **FastAPI serves
  the JSON API and the built React app**, deployed on Heroku with `heroku.yml`.
- **Reproducible data pipeline**: `python -m backend.app.fetch_data
  --decision-month 2026-01` fetches in bounded chunks with retries, preserves
  the raw responses, validates the data, reports conflicts and coverage, and
  writes a manifest. The app never calls Elexon at request time.

### 2. Data understanding (1:00–2:00)
- Open `docs/data-notes.md`. The API details were verified against the docs
  and real responses.
- **publishTime vs startTime**: WINDFOR can only be filtered by publish time;
  it keeps every publication (8 a day).
- Resolution mismatch: hourly forecasts vs half-hourly actuals, so each hour
  is compared with the mean of its two half-hours.
- Docs vs reality: the publication times differ by an hour from the
  documented schedule, so the code relies on the real `publishTime`.

### 3. Core logic (2:00–3:30)
- Open `backend/app/analysis.py`:
  - `delivery_hours`: London calendar day, so 23 or 25 hours on clock-change
    days;
  - `select_forecasts`: `publish_time <= cutoff`, then the latest per hour.
    **It doesn't take actuals as an input**, so no look-ahead is possible by
    construction;
  - `hourly_actuals`: NaN propagates, so a missing half makes the hour
    missing;
  - `coverage` and `error_metrics`: MAE, RMSE, bias and percentiles; no MAPE
    because output can be near zero.

### 4. Quality and practices (3:30–5:00)
- Run `pytest` live (82 tests). Highlight the tests for:
  - the cutoff boundary (10:00 is used, 10:01 is not);
  - missing data staying `null`;
  - 31 Jan → 1 Feb;
  - clock-change days;
  - "no forecast after the cutoff" across all of January.
- API validation (422), and `null` rather than NaN in JSON.
- Small staged commits, a checklist, dedicated dev ports, a Docker image that
  runs as a non-root user, no secrets in the repo.
- **AI assistance**: built with Claude Code. Rules are enforced by tests, and
  the README discloses it.

---

## After recording

- Upload as **Unlisted**, and check the link in an **incognito** window.
- Check that the GitHub repo is **public** and the Heroku app opens in an
  incognito window.
