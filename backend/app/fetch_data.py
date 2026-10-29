"""Reproducible data preparation: fetch, preserve, clean and document one decision month.

Run from the repository root:
    python -m backend.app.fetch_data --decision-month 2026-01

Writes:
    data/raw/<month>/*.json        original API response bodies, byte for byte (gitignored)
    data/processed/actuals.csv     WIND actuals, half-hourly, UTC
    data/processed/forecasts.csv   full WINDFOR publication history for the delivery days, UTC
    data/processed/manifest.json   sources, request ranges, retrieval times, row counts,
                                   coverage and assumptions

The dashboard only reads data/processed. It never calls Elexon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import analysis, elexon

LONDON = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
DEFAULT_LOOKBACK_DAYS = 4
ATTRIBUTION = "Contains BMRS data © Elexon Limited copyright and database right 2026."
LICENCE_URL = "https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/"

ASSUMPTIONS = [
    "Decision dates are every calendar day of the decision month.",
    "Delivery day = the Europe/London calendar day after the decision date.",
    "The decision cutoff is configurable in the app; 10:00 Europe/London is a demo assumption, not a market rule.",
    "Forecasts are fetched by publish time from LOOKBACK days before the first decision date to the end of the "
    "last decision date, so any cutoff on any decision date can find its latest eligible publications.",
    "Forecast rows are kept if their target hour (startTime) is in a delivery day, whatever their publish time, "
    "so publications from before the decision month are not discarded.",
    "Actuals (FUELHH, fuelType WIND only) are fetched by settlement date with one day of margin each side, then "
    "filtered by startTime to the delivery days. Actuals are for evaluation only.",
    "All timestamps are parsed as timezone-aware UTC and written as ISO-8601 strings ending in 'Z'.",
    "Exact duplicate rows are removed. Conflicting actuals with different publish times keep the latest revision; "
    "any other conflict is set to missing. All conflicts are reported.",
    "Missing or invalid values are kept as missing (empty in CSV). Nothing is interpolated or filled.",
    "Rows without a usable timestamp, or off the 30-minute (actuals) / hourly (forecasts) grid, are removed and counted.",
    "Units: generation in MW (FUELHH: average MW over the half-hour; WINDFOR: hourly MW forecast).",
    "Scope: both datasets cover wind farms with operational metering on the transmission network, not total GB wind.",
]


@dataclass(frozen=True)
class Plan:
    """Every date range derived from the decision month."""

    month: str
    decision_dates: list[date]
    delivery_start: datetime  # London midnight of the first delivery day
    delivery_end: datetime  # London midnight after the last delivery day (exclusive)
    publish_start: datetime
    publish_end: datetime
    settlement_first: date
    settlement_last: date
    lookback_days: int


def plan_for_month(month: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> Plan:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError(f"--decision-month must be YYYY-MM, got {month!r}")
    year, mon = map(int, month.split("-"))
    first = date(year, mon, 1)
    next_month = date(year + mon // 12, mon % 12 + 1, 1)
    decision_dates = [first + timedelta(days=i) for i in range((next_month - first).days)]

    def london_midnight(d: date) -> datetime:
        return datetime.combine(d, time(0), tzinfo=LONDON)

    return Plan(
        month=month,
        decision_dates=decision_dates,
        delivery_start=london_midnight(decision_dates[0] + timedelta(days=1)),
        delivery_end=london_midnight(decision_dates[-1] + timedelta(days=2)),
        publish_start=london_midnight(decision_dates[0] - timedelta(days=lookback_days)),
        publish_end=london_midnight(decision_dates[-1] + timedelta(days=1)),
        settlement_first=decision_dates[0],
        settlement_last=decision_dates[-1] + timedelta(days=2),
        lookback_days=lookback_days,
    )


# ---------------------------------------------------------------- raw preservation


def _display_path(path: Path) -> str:
    """Path relative to the repository root when inside it, otherwise absolute."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def save_raw(responses: list[elexon.Response], raw_dir: Path) -> list[dict]:
    """Write each response body unchanged; return a manifest entry per request."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for r in responses:
        span = "_".join(re.sub(r"[^0-9]", "", v)[:12] for k, v in r.params.items() if k != "fuelType")
        path = raw_dir / f"{r.dataset.lower()}_{span}.json"
        path.write_bytes(r.body)
        entries.append(
            {
                "dataset": r.dataset,
                "url": r.url,
                "params": r.params,
                "status": r.status,
                "attempts": r.attempts,
                "retrieved_at_utc": r.retrieved_at_utc,
                "bytes": len(r.body),
                "rows": len(r.rows()),
                "raw_file": _display_path(path),
                "sha256": hashlib.sha256(r.body).hexdigest(),
            }
        )
    return entries


# ---------------------------------------------------------------- coverage


def actual_coverage(actuals: pd.DataFrame, plan: Plan) -> dict:
    expected = pd.date_range(plan.delivery_start, plan.delivery_end, freq="30min", inclusive="left").tz_convert("UTC")
    present = set(actuals.loc[actuals["generation_mw"].notna(), "start_time"])
    missing = [t for t in expected if t not in present]
    by_day = {}
    for d in plan.decision_dates:
        delivery = d + timedelta(days=1)
        day = [t for t in expected if t.tz_convert(LONDON).date() == delivery]
        by_day[delivery.isoformat()] = sum(t in present for t in day) / len(day)
    return {
        "expected_half_hours": len(expected),
        "present_half_hours": len(expected) - len(missing),
        "coverage": (len(expected) - len(missing)) / len(expected),
        "missing_half_hours": [elexon._utc_iso(t) for t in missing],
        "by_delivery_day": by_day,
    }


def forecast_coverage(forecasts: pd.DataFrame, plan: Plan) -> dict:
    hours = pd.date_range(plan.delivery_start, plan.delivery_end, freq="h", inclusive="left").tz_convert("UTC")
    any_forecast = set(forecasts.loc[forecasts["generation_mw"].notna(), "start_time"])
    at_default = {}
    for d in plan.decision_dates:
        table = analysis.select_forecasts(forecasts, d, analysis.DEFAULT_CUTOFF)
        at_default[d.isoformat()] = float(table["forecast_mw"].notna().mean())
    publish_london = forecasts["publish_time"].drop_duplicates().dt.tz_convert(LONDON)
    return {
        "expected_delivery_hours": len(hours),
        "hours_with_any_forecast": sum(h in any_forecast for h in hours),
        "coverage_any_publication": sum(h in any_forecast for h in hours) / len(hours),
        "coverage_at_default_cutoff_by_decision_date": at_default,
        "default_cutoff_london": analysis.DEFAULT_CUTOFF.strftime("%H:%M"),
        "publications_per_london_day": {
            str(k): int(v) for k, v in publish_london.dt.date.value_counts().sort_index().items()
        },
    }


# ---------------------------------------------------------------- main


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if value is pd.NA:
        return None
    return str(value)


def run(plan: Plan, raw_root: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR, client=None) -> dict:
    raw_dir = raw_root / plan.month
    own_client = client is None
    client = client or elexon.make_client()
    try:
        print(f"Fetching FUELHH (WIND) settlement dates {plan.settlement_first} to {plan.settlement_last}...")
        actual_responses = elexon.fetch_fuelhh_wind(client, plan.settlement_first, plan.settlement_last)
        print(f"Fetching WINDFOR publications {plan.publish_start.isoformat()} to {plan.publish_end.isoformat()}...")
        forecast_responses = elexon.fetch_windfor(client, plan.publish_start, plan.publish_end)
    finally:
        if own_client:
            client.close()

    requests = save_raw(actual_responses + forecast_responses, raw_dir)
    actual_rows = [row for r in actual_responses for row in r.rows()]
    forecast_rows = [row for r in forecast_responses for row in r.rows()]

    actuals, actual_report = elexon.clean_actuals(actual_rows, plan.delivery_start, plan.delivery_end)
    forecasts, forecast_report = elexon.clean_forecasts(forecast_rows, plan.delivery_start, plan.delivery_end)

    processed_dir.mkdir(parents=True, exist_ok=True)
    elexon.to_csv_utc(actuals, processed_dir / "actuals.csv")
    elexon.to_csv_utc(forecasts, processed_dir / "forecasts.csv")

    manifest = {
        "generated_at_utc": elexon._utc_iso(pd.Timestamp.now(tz="UTC")),
        "command": f"python -m backend.app.fetch_data --decision-month {plan.month}"
        + (f" --lookback-days {plan.lookback_days}" if plan.lookback_days != DEFAULT_LOOKBACK_DAYS else ""),
        "source": {
            "provider": "Elexon Insights Solution (BMRS) API",
            "base_url": elexon.BASE_URL,
            "datasets": {
                "actuals": f"{elexon.BASE_URL}{elexon.FUELHH_PATH} (fuelType=WIND)",
                "forecasts": f"{elexon.BASE_URL}{elexon.WINDFOR_PATH}",
            },
            "attribution": ATTRIBUTION,
            "licence": LICENCE_URL,
        },
        "decision_month": plan.month,
        "decision_dates": [plan.decision_dates[0].isoformat(), plan.decision_dates[-1].isoformat()],
        "delivery_window_london": [plan.delivery_start.isoformat(), plan.delivery_end.isoformat()],
        "request_ranges": {
            "fuelhh_settlement_dates": [plan.settlement_first.isoformat(), plan.settlement_last.isoformat()],
            "windfor_publish_times_london": [plan.publish_start.isoformat(), plan.publish_end.isoformat()],
            "lookback_days": plan.lookback_days,
            "chunk_days": elexon.CHUNK_DAYS,
        },
        "requests": requests,
        "row_counts": {
            "actuals_raw": len(actual_rows),
            "actuals_processed": len(actuals),
            "forecasts_raw": len(forecast_rows),
            "forecasts_processed": len(forecasts),
        },
        "cleaning": {"actuals": actual_report, "forecasts": forecast_report},
        "coverage": {"actuals": actual_coverage(actuals, plan), "forecasts": forecast_coverage(forecasts, plan)},
        "assumptions": [a.replace("LOOKBACK", str(plan.lookback_days)) for a in ASSUMPTIONS],
        "outputs": {
            name: hashlib.sha256((processed_dir / name).read_bytes()).hexdigest()
            for name in ("actuals.csv", "forecasts.csv")
        },
    }
    (processed_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=_json_default) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--decision-month", required=True, help="Decision month, YYYY-MM (e.g. 2026-01)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Days of forecast publications to fetch before the first decision date (default %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        plan = plan_for_month(args.decision_month, args.lookback_days)
    except ValueError as exc:
        parser.error(str(exc))

    manifest = run(plan)
    cov = manifest["coverage"]
    print(
        json.dumps(
            {
                "row_counts": manifest["row_counts"],
                "actual_coverage": cov["actuals"]["coverage"],
                "forecast_coverage_any_publication": cov["forecasts"]["coverage_any_publication"],
                "actual_conflicts": manifest["cleaning"]["actuals"]["conflicting_start_times"],
                "forecast_conflicts": manifest["cleaning"]["forecasts"]["conflicting_keys_set_to_missing"],
                "requests": len(manifest["requests"]),
            },
            indent=2,
        )
    )
    print(f"Wrote {_display_path(PROCESSED_DIR)}/ (actuals.csv, forecasts.csv, manifest.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
