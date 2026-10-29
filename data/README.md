# Data

| Folder | Contents | In git? |
|---|---|---|
| `raw/<month>/` | Original Elexon API response bodies, byte for byte, one file per request | No (gitignored) |
| `processed/` | Normalised `actuals.csv`, `forecasts.csv` and `manifest.json` | Yes |

Recreate both from the repository root:

```bash
python -m backend.app.fetch_data --decision-month 2026-01
```

`processed/manifest.json` records the source URLs, request ranges, retrieval
times, SHA-256 fingerprints of the raw and processed files, row counts,
cleaning counts, coverage and every preparation assumption.

## Source and attribution

Contains BMRS data © Elexon Limited copyright and database right 2026.
Licence: https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/

Datasets: FUELHH (`fuelType = WIND`) actuals and WINDFOR wind forecasts, from
the Elexon Insights Solution API (`https://data.elexon.co.uk/bmrs/api/v1`).
This project is not endorsed by Elexon.
