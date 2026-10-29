"""Re-create the committed data snapshot from the Elexon API.

Run from the backend/ directory:
    python -m scripts.build_snapshot

Writes:
    data/raw/fuelhh_wind.json, data/raw/windfor.json   (raw downloads, gitignored)
    data/snapshot/actuals.csv                          (WIND actuals, 30-min)
    data/snapshot/forecasts.csv                        (all WINDFOR publications, hourly)
    data/snapshot/metadata.json                        (ranges, counts, data-quality report)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from app import elexon

LONDON = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SNAPSHOT_DIR = ROOT / "data" / "snapshot"

# Decision dates are 1-31 Jan 2026, so delivery days are 2 Jan - 1 Feb 2026
# (Europe/London). The window is [first delivery day 00:00, day after last 00:00).
DELIVERY_START = datetime(2026, 1, 2, tzinfo=LONDON)
DELIVERY_END = datetime(2026, 2, 2, tzinfo=LONDON)

# Forecasts: anything published from a few days before the first decision date
# up to the end of the last decision date, so any cutoff time can be used.
PUBLISH_START = datetime(2025, 12, 28, tzinfo=LONDON)
PUBLISH_END = datetime(2026, 2, 1, tzinfo=LONDON)

# Actuals: one settlement day of margin each side; rows are filtered by
# start_time afterwards, so the exact settlement-date range is not critical.
SETTLEMENT_FIRST = date(2026, 1, 1)
SETTLEMENT_LAST = date(2026, 2, 2)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with elexon.make_client() as client:
        print("Downloading FUELHH (WIND) actuals...")
        raw_actuals = elexon.fetch_fuelhh_wind(client, SETTLEMENT_FIRST, SETTLEMENT_LAST)
        print("Downloading WINDFOR forecasts...")
        raw_forecasts = elexon.fetch_windfor(client, PUBLISH_START, PUBLISH_END)

    (RAW_DIR / "fuelhh_wind.json").write_text(json.dumps(raw_actuals))
    (RAW_DIR / "windfor.json").write_text(json.dumps(raw_forecasts))

    actuals, actuals_report = elexon.clean_actuals(raw_actuals, DELIVERY_START, DELIVERY_END)
    forecasts, forecasts_report = elexon.clean_forecasts(raw_forecasts, DELIVERY_START, DELIVERY_END)

    elexon.to_csv_utc(actuals, SNAPSHOT_DIR / "actuals.csv")
    elexon.to_csv_utc(forecasts, SNAPSHOT_DIR / "forecasts.csv")

    quality = quality_report(actuals, forecasts)
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": elexon.BASE_URL,
        "delivery_window_london": [DELIVERY_START.isoformat(), DELIVERY_END.isoformat()],
        "forecast_publish_window_london": [PUBLISH_START.isoformat(), PUBLISH_END.isoformat()],
        "actual_settlement_dates": [SETTLEMENT_FIRST.isoformat(), SETTLEMENT_LAST.isoformat()],
        "actuals": actuals_report,
        "forecasts": forecasts_report,
        "quality": quality,
    }
    (SNAPSHOT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({k: metadata[k] for k in ("actuals", "forecasts", "quality")}, indent=2))
    print(f"Snapshot written to {SNAPSHOT_DIR}")


def quality_report(actuals: pd.DataFrame, forecasts: pd.DataFrame) -> dict:
    """Coverage and publication-schedule checks. Reported, never 'fixed'."""
    expected = pd.date_range(DELIVERY_START, DELIVERY_END, freq="30min", inclusive="left").tz_convert("UTC")
    present = set(actuals.loc[actuals["generation_mw"].notna(), "start_time"])
    missing = [t for t in expected if t not in present]

    publish_london = forecasts["publish_time"].drop_duplicates().dt.tz_convert(LONDON)
    pubs_per_day = publish_london.dt.date.value_counts().sort_index()
    times_of_day = publish_london.dt.strftime("%H:%M").value_counts().sort_index()

    return {
        "actual_half_hours_expected": len(expected),
        "actual_half_hours_present": len(expected) - len(missing),
        "actual_half_hours_missing": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in missing],
        "forecast_publications_per_london_day": {str(d): int(n) for d, n in pubs_per_day.items()},
        "forecast_publication_times_london": {t: int(n) for t, n in times_of_day.items()},
    }


if __name__ == "__main__":
    main()
