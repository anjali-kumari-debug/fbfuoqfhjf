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
- Pick decision date **15 Jan**. The delivery day (**16 Jan**) is worked out
  for you, and every time is labelled **Europe/London**.
- Point to the **decision time box and its badge**: *"10:00 is our demo
  assumption, not a market rule. Set it to your real cutoff."*
- Hover the forecast chart: each hour shows the forecast MW and **the
  publication it came from**. *"This is exactly what you could have seen at
  10:00, nothing published later."*
- Read the "Which forecast publication was used?" box: different hours *can*
  come from different publications.
- Set the decision time to **01:00**: a **partial forecast** notice appears
  and the last hours of the chart are blank. *"When no forecast existed yet,
  we tell you. We never show it as zero."* Set it back to 10:00.
- Click **"See how this forecast compared with actual generation"**.

### 3. Accuracy (2:15–4:00)
- That link opens the accuracy view for one day; actuals are clearly marked
  **retrospective**. Click **All of January**.
- Headline cards: **MAE about 2,000 MW, bias +1,730 MW, 744 / 744 hours
  matched**. The short guide explains each metric and the error sign.
- *"The key finding: forecasts were consistently **too high**, by about
  1.7 GW on average. If you bought only to cover the gap left by the
  forecast wind, you would usually have been short."* Show it in the
  actual-vs-forecast chart (the blue line sits above the orange) and in the
  mostly red daily bias bars.
- *"Some days are far worse"*: click **28 Jan** in the bias chart to open
  that decision.
- Change the decision time to **16:00**: MAE drops to about 1,870 MW.
  *"Later forecasts are better. This quantifies what waiting buys you."*

### 4. Honest limits and next steps (4:00–5:00)
- The data covers **metered transmission-connected wind farms (about 82% of
  GB wind)**, not embedded wind.
- No demand data is included, so this is **not a procurement-volume
  calculator**. We report forecasts and their errors, one input to the
  buying decision.
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
- Run `pytest` live (117 tests). Highlight the tests for:
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
