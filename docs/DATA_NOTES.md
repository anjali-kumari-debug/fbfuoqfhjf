# Data notes (Stage 1 findings)

Checked against the live Elexon Insights API on 2026-10-28.
API description: `https://data.elexon.co.uk/swagger/v1/swagger.json`.
Base URL: `https://data.elexon.co.uk/bmrs/api/v1`.

## Actuals: FUELHH stream

`GET /datasets/FUELHH/stream?settlementDateFrom=YYYY-MM-DD&settlementDateTo=YYYY-MM-DD&fuelType=WIND`

- Filters: `settlementDateFrom/To` (format exactly `yyyy-MM-dd`) **or**
  `publishDateTimeFrom/To`, not both. `fuelType=WIND` filters on the server.
- Returns a JSON list. Example row:
  `{"dataset":"FUELHH","publishTime":"2026-01-02T00:00:00Z","startTime":"2026-01-01T23:30:00Z","settlementDate":"2026-01-01","settlementPeriod":48,"fuelType":"WIND","generation":15538}`
- Resolution: **30 minutes**, 48 rows per settlement day (periods 1 to 48).
  `generation` is the average MW over the half-hour.
- Timestamps are UTC with a `Z` suffix.
- 1 Feb 2026 actuals are available (48 rows).

## Forecasts: WINDFOR stream

`GET /datasets/WINDFOR/stream?publishDateTimeFrom=<UTC ISO>&publishDateTimeTo=<UTC ISO>`

- The only filters are on **publish time**. With no filter it returns only the
  latest forecast.
- Example row:
  `{"dataset":"WINDFOR","publishTime":"2026-01-01T11:30:00Z","startTime":"2026-01-01T00:00:00Z","generation":19960}`
- Resolution: **hourly** (`startTime` always on the hour).
- Publications: **8 per day** at 02:30, 04:30, 07:30, 09:30, 11:30, 15:30,
  18:30 and 22:30 UTC (seen every day from 29 Dec 2025 to 4 Jan 2026).
- Each publication has 73 hourly values. They run from 21:00 UTC on the day
  before publication to 21:00 UTC two days after it. So the **09:30 publication
  on decision day D covers the whole of delivery day D+1**.
- Historical publications are kept. Late-December 2025 publications are
  available.
- A 7-day publish-time range returned 4,088 rows (about 460 KB) in one request.
  The snapshot script will fetch in chunks of at most 7 days to stay safe.

## What this means for the app

- **Default cutoff 10:00 Europe/London** = 10:00 UTC in January. The latest
  eligible publication is usually **09:30 UTC** that day (assuming the 09:30
  publication isn't missing).
- **Resolution mismatch (DECIDED 2026-10-28):** forecasts are hourly, actuals
  are half-hourly. We score on the **hourly grid**: the forecast for hour `T`
  is compared with the **mean of the two actual half-hours** starting at `T`
  and `T+30min`. If either half-hour is missing, the hour's actual is missing
  (never filled or interpolated). The UI and README must state this. Charts
  may still show the raw half-hourly actuals.
- **Expected intervals per delivery day:** count them from the Europe/London
  day boundaries, never hard-code 24 or 48 (clock-change days have 23 or 25
  hours).
- **Fetch ranges for the snapshot:**
  - WINDFOR publish times: 2025-12-28T00:00Z to 2026-02-01T00:00Z. This covers
    any cutoff time on any January decision date.
  - FUELHH settlement dates: 2026-01-01 to 2026-02-01. Filter by `startTime`
    converted to Europe/London; don't rely on `settlementDate`.
