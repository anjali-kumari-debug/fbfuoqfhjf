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
    """Decision cutoff as a UTC timestamp (cutoff is local Europe/London time).

    Clock-change days (never in January): a local time that does not exist
    (e.g. 01:30 on the spring-forward day) is read with the pre-change offset,
    and a time that occurs twice (01:30 on the autumn day) uses its first
    occurrence (BST). This follows Python's zoneinfo rules (fold=0).
    """
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


def one_value_per_key(df: pd.DataFrame, key: list[str]) -> pd.DataFrame:
    """At most one generation value per key, without picking arbitrarily.

    Exact duplicates collapse to one row. An empty duplicate is missing data, not
    a competing value, so it never hides a real value. If a key has two or more
    *different* real values, there is no principled winner, so its value becomes
    NaN (missing), never a guess.
    """
    df = df.drop_duplicates(subset=[*key, "generation_mw"])
    dup = df.duplicated(key, keep=False)
    if not dup.any():
        return df
    groups = df[dup]

    def single_value(s: pd.Series) -> float:
        values = s.dropna().unique()
        return float(values[0]) if len(values) == 1 else np.nan

    resolved = groups.drop_duplicates(key).set_index(key)
    resolved["generation_mw"] = groups.groupby(key, sort=False)["generation_mw"].agg(single_value)
    return pd.concat([df[~dup], resolved.reset_index()])


def select_forecasts(forecasts: pd.DataFrame, decision_date: date, cutoff: time) -> pd.DataFrame:
    """Latest forecast published at or before the cutoff, for each delivery hour.

    Returns one row per delivery hour (index start_time, UTC) with columns
    forecast_mw and publish_time. Both are NaN/NaT when no eligible forecast
    exists. A row with no usable value (missing, or conflicting duplicates) is
    not a forecast, so the hour falls back to the latest earlier publication.
    Input order does not matter.
    """
    cutoff_utc = cutoff_datetime(decision_date, cutoff)
    hours = delivery_hours(decision_date)
    eligible = forecasts[(forecasts["publish_time"] <= cutoff_utc) & forecasts["start_time"].isin(hours)]
    eligible = one_value_per_key(eligible, ["publish_time", "start_time"])
    eligible = eligible[eligible["generation_mw"].notna()]
    latest = (
        eligible.sort_values("publish_time", kind="stable")
        .drop_duplicates("start_time", keep="last")
        .set_index("start_time")
    )
    out = pd.DataFrame(index=hours)
    out["forecast_mw"] = latest["generation_mw"].reindex(hours).astype(float)
    out["publish_time"] = latest["publish_time"].reindex(hours)
    return out


def hourly_actuals(actuals: pd.DataFrame, hours: pd.DatetimeIndex) -> pd.Series:
    """Mean of the two half-hours in each hour. NaN if either half is missing.

    Duplicate half-hours are handled by one_value_per_key (conflicts -> missing).
    """
    half_hourly = (
        one_value_per_key(actuals[["start_time", "generation_mw"]], ["start_time"])
        .set_index("start_time")["generation_mw"]
        .astype(float)
    )
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
    """Interval counts, reported separately, out of the intervals expected.

    expected: delivery intervals (hours) in the London delivery day(s)
    forecast: intervals with a selected (eligible) forecast
    actual:   intervals with an actual value
    matched:  intervals with both, i.e. the only ones used by the metrics
    """
    expected = len(table)
    forecast = int(table["forecast_mw"].notna().sum())
    actual = int(table["actual_mw"].notna().sum())
    matched = int(table["error_mw"].notna().sum())
    ratio = lambda n: n / expected if expected else None  # noqa: E731
    return {
        "expected_intervals": expected,
        "forecast_intervals": forecast,
        "actual_intervals": actual,
        "matched_intervals": matched,
        "forecast_coverage": ratio(forecast),
        "actual_coverage": ratio(actual),
        "matched_coverage": ratio(matched),
    }


def error_metrics(errors: pd.Series) -> dict:
    """MAE, RMSE, mean error (bias) and error percentiles, in MW.

    NaN errors are ignored (they are reported through coverage instead).
    All values are None when there are no errors to score.
    """
    values = errors.dropna().to_numpy(dtype=float)
    keys = ["mae_mw", "rmse_mw", "bias_mw", "p90_abs_error_mw"] + [f"p{p}_mw" for p in PERCENTILES]
    if values.size == 0:
        return {"n": 0, **dict.fromkeys(keys)}
    result = {
        "n": int(values.size),
        "mae_mw": float(np.mean(np.abs(values))),
        "rmse_mw": float(np.sqrt(np.mean(values**2))),
        "bias_mw": float(np.mean(values)),
        # 9 in 10 matched intervals missed by less than this (size of miss, either direction).
        "p90_abs_error_mw": float(np.percentile(np.abs(values), 90)),
    }
    for p, v in zip(PERCENTILES, np.percentile(values, PERCENTILES)):
        result[f"p{p}_mw"] = float(v)
    return result


RECENT_WINDOW_DAYS = 7


def recent_error_profile(
    actuals: pd.DataFrame,
    forecasts: pd.DataFrame,
    decision_date: date,
    cutoff: time,
    window_days: int = RECENT_WINDOW_DAYS,
) -> dict:
    """The forecast's recent track record, as it was known at this decision's cutoff.

    Pools the errors of the previous `window_days` decisions (each with its own
    cutoff and selected forecasts), scored only against actuals that had been
    *published* by this decision's cutoff. Today's and future outcomes are never
    used, so this is safe to show next to today's forecast. It describes past
    errors; it does not change the forecast. Metrics are None when no matched
    history exists yet (e.g. at the start of the data).
    """
    if "publish_time" not in actuals:
        raise ValueError("actuals need a publish_time column to know what was published by the cutoff")
    cutoff_utc = cutoff_datetime(decision_date, cutoff)
    known = actuals[actuals["publish_time"] <= cutoff_utc]
    history = [decision_date - timedelta(days=k) for k in range(1, window_days + 1)]
    errors = [decision_table(known, forecasts, d, cutoff)["error_mw"] for d in history]
    pooled = pd.concat(errors)
    return {
        "window_first_decision": history[-1].isoformat(),
        "window_last_decision": history[0].isoformat(),
        "decisions_with_data": int(sum(e.notna().any() for e in errors)),
        "matched_intervals": int(pooled.notna().sum()),
        **error_metrics(pooled),
    }


def error_histogram(errors: pd.Series, bin_mw: int = 500) -> list[dict]:
    """Counts of matched-interval errors in fixed-width bins, e.g. [-500, 0), [0, 500)."""
    values = errors.dropna().to_numpy(dtype=float)
    if values.size == 0:
        return []
    low = np.floor(values.min() / bin_mw) * bin_mw
    high = np.floor(values.max() / bin_mw) * bin_mw + bin_mw
    edges = np.arange(low, high + bin_mw, bin_mw)
    counts, _ = np.histogram(values, bins=edges)
    return [
        {"from_mw": int(edges[i]), "to_mw": int(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]


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
