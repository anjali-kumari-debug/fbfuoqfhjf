"""Core logic: forecast selection at a decision cutoff, alignment and metrics.

Rules (see CLAUDE.md):
- Delivery day = the Europe/London calendar day after the decision date.
- For each delivery hour, use the forecast with the latest publish_time that is
  <= the decision cutoff (decision date + cutoff time, Europe/London).
  Forecast selection never sees actuals.
- Forecasts are hourly and actuals half-hourly. The actual for hour T is the
  mean of the half-hours starting at T and T+30min. If either is missing, the
  hour's actual is missing.
- Missing data stays NaN and is counted in coverage, never filled or dropped.
- error = forecast - actual (MW). Positive means over-forecast.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LONDON = ZoneInfo("Europe/London")
DEFAULT_CUTOFF = time(10, 0)  # demo assumption, not a market rule
PERCENTILES = (10, 25, 50, 75, 90)
# Written by `python -m backend.app.fetch_data`; the app never calls Elexon itself.
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


# ---------------------------------------------------------------- loading


def load_data(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read processed actuals.csv and forecasts.csv with timezone-aware UTC timestamps."""
    actuals = pd.read_csv(data_dir / "actuals.csv")
    forecasts = pd.read_csv(data_dir / "forecasts.csv")
    for df in (actuals, forecasts):
        for col in ("start_time", "publish_time"):
            if col in df:
                df[col] = pd.to_datetime(df[col], utc=True, format="ISO8601")
        df["generation_mw"] = pd.to_numeric(df["generation_mw"], errors="coerce")
    return actuals, forecasts


# ---------------------------------------------------------------- time helpers


def parse_cutoff(text: str) -> time:
    """Parse 'HH:MM' (24-hour). Raises ValueError for anything else."""
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text or "")
    if not match:
        raise ValueError(f"Cutoff must be HH:MM between 00:00 and 23:59, got {text!r}")
    return time(int(match.group(1)), int(match.group(2)))


def cutoff_datetime(decision_date: date, cutoff: time) -> pd.Timestamp:
    """Decision cutoff as a UTC timestamp (cutoff is local Europe/London time)."""
    local = datetime.combine(decision_date, cutoff, tzinfo=LONDON)
    return pd.Timestamp(local).tz_convert("UTC")


def delivery_date(decision_date: date) -> date:
    return decision_date + timedelta(days=1)


def delivery_hours(decision_date: date) -> pd.DatetimeIndex:
    """UTC start times of every hour in the London delivery day.

    Usually 24 hours, but 23 or 25 on clock-change days.
    """
    day = delivery_date(decision_date)
    start = pd.Timestamp(datetime.combine(day, time(0), tzinfo=LONDON))
    end = pd.Timestamp(datetime.combine(day + timedelta(days=1), time(0), tzinfo=LONDON))
    hours = pd.date_range(start, end, freq="h", inclusive="left").tz_convert("UTC")
    return hours.rename("start_time")


# ---------------------------------------------------------------- selection and alignment


def select_forecasts(forecasts: pd.DataFrame, decision_date: date, cutoff: time) -> pd.DataFrame:
    """Latest forecast published at or before the cutoff, for each delivery hour.

    Returns one row per delivery hour (index start_time, UTC) with columns
    forecast_mw and publish_time. Both are NaN/NaT when no eligible forecast
    exists. A row with no generation value is not treated as a forecast.
    """
    cutoff_utc = cutoff_datetime(decision_date, cutoff)
    hours = delivery_hours(decision_date)
    eligible = forecasts[
        (forecasts["publish_time"] <= cutoff_utc)
        & forecasts["start_time"].isin(hours)
        & forecasts["generation_mw"].notna()
    ]
    latest = (
        eligible.sort_values("publish_time")
        .drop_duplicates("start_time", keep="last")
        .set_index("start_time")
    )
    out = pd.DataFrame(index=hours)
    out["forecast_mw"] = latest["generation_mw"].reindex(hours).astype(float)
    out["publish_time"] = latest["publish_time"].reindex(hours)
    return out


def hourly_actuals(actuals: pd.DataFrame, hours: pd.DatetimeIndex) -> pd.Series:
    """Mean of the two half-hours in each hour. NaN if either half is missing."""
    half_hourly = actuals.set_index("start_time")["generation_mw"].astype(float)
    first = half_hourly.reindex(hours).to_numpy()
    second = half_hourly.reindex(hours + pd.Timedelta(minutes=30)).to_numpy()
    return pd.Series((first + second) / 2, index=hours, name="actual_mw")


def decision_table(
    actuals: pd.DataFrame, forecasts: pd.DataFrame, decision_date: date, cutoff: time
) -> pd.DataFrame:
    """Hour-by-hour table for one decision: forecast, actual, error, lead time."""
    table = select_forecasts(forecasts, decision_date, cutoff)
    table["actual_mw"] = hourly_actuals(actuals, table.index)
    table["error_mw"] = table["forecast_mw"] - table["actual_mw"]
    lead_time = table.index.to_series() - table["publish_time"]
    table["lead_time_hours"] = lead_time.dt.total_seconds() / 3600
    return table


# ---------------------------------------------------------------- coverage and metrics


def coverage(table: pd.DataFrame) -> dict:
    """Counts of hours with data, out of the hours expected in the delivery day."""
    expected = len(table)
    forecast = int(table["forecast_mw"].notna().sum())
    actual = int(table["actual_mw"].notna().sum())
    paired = int(table["error_mw"].notna().sum())
    ratio = lambda n: n / expected if expected else None  # noqa: E731
    return {
        "expected_hours": expected,
        "forecast_hours": forecast,
        "actual_hours": actual,
        "paired_hours": paired,
        "forecast_coverage": ratio(forecast),
        "actual_coverage": ratio(actual),
        "paired_coverage": ratio(paired),
    }


def error_metrics(errors: pd.Series) -> dict:
    """MAE, RMSE, mean error (bias) and error percentiles, in MW.

    NaN errors are ignored (they are reported through coverage instead).
    All values are None when there are no errors to score.
    """
    values = errors.dropna().to_numpy(dtype=float)
    keys = ["mae_mw", "rmse_mw", "bias_mw"] + [f"p{p}_mw" for p in PERCENTILES]
    if values.size == 0:
        return {"n": 0, **dict.fromkeys(keys)}
    result = {
        "n": int(values.size),
        "mae_mw": float(np.mean(np.abs(values))),
        "rmse_mw": float(np.sqrt(np.mean(values**2))),
        "bias_mw": float(np.mean(values)),
    }
    for p, v in zip(PERCENTILES, np.percentile(values, PERCENTILES)):
        result[f"p{p}_mw"] = float(v)
    return result


def accuracy(
    actuals: pd.DataFrame, forecasts: pd.DataFrame, decision_dates: list[date], cutoff: time
) -> dict:
    """Per-day and overall accuracy for a set of decision dates at one cutoff.

    Returns {"days": DataFrame (one row per decision date),
             "hours": DataFrame (every delivery hour, all days),
             "overall": dict of coverage + metrics}.
    """
    day_rows, tables = [], []
    for d in decision_dates:
        table = decision_table(actuals, forecasts, d, cutoff)
        table["decision_date"] = d
        tables.append(table)
        day_rows.append(
            {"decision_date": d, "delivery_date": delivery_date(d)}
            | coverage(table)
            | error_metrics(table["error_mw"])
        )
    hours = pd.concat(tables) if tables else pd.DataFrame()
    overall = coverage(hours) | error_metrics(hours["error_mw"]) if tables else {}
    return {"days": pd.DataFrame(day_rows), "hours": hours, "overall": overall}
