"""FastAPI app: JSON API over the processed Elexon data, plus the built React app.

Run from backend/:  ../.venv/bin/uvicorn app.main:app --reload
Interactive docs:   http://127.0.0.1:8000/docs

If frontend/dist exists (after `npm run build`, or inside Docker), it is served
at "/" so one service delivers both the UI and the API.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import analysis

FRONTEND_DIST = Path(
    os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist")
)
FIRST_DECISION_DATE = date(2026, 1, 1)
LAST_DECISION_DATE = date(2026, 1, 31)
HISTOGRAM_BIN_MW = 500

app = FastAPI(title="Wind forecast accuracy API", version="1.0.0")


@lru_cache
def dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load data/processed once and reuse it for every request (no API calls at request time)."""
    return analysis.load_data()


# ---------------------------------------------------------------- input checks


def parse_cutoff_param(cutoff: str) -> time:
    try:
        return analysis.parse_cutoff(cutoff)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def parse_decision_date(text: str) -> date:
    try:
        d = date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"date must be YYYY-MM-DD, got {text!r}") from exc
    if not FIRST_DECISION_DATE <= d <= LAST_DECISION_DATE:
        raise HTTPException(
            status_code=422,
            detail=f"date must be between {FIRST_DECISION_DATE} and {LAST_DECISION_DATE}",
        )
    return d


def decision_dates() -> list[date]:
    days = (LAST_DECISION_DATE - FIRST_DECISION_DATE).days + 1
    return [FIRST_DECISION_DATE + timedelta(days=i) for i in range(days)]


# ---------------------------------------------------------------- JSON helpers


def clean(value):
    """Make a value JSON-safe: NaN/NaT -> None, timestamps -> UTC ISO strings."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) else float(value)
    return value


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def clean_dict(d: dict) -> dict:
    return {k: clean(v) for k, v in d.items()}


def histogram(errors: pd.Series, bin_mw: int = HISTOGRAM_BIN_MW) -> list[dict]:
    """Counts of errors in fixed-width bins, e.g. [-500, 0), [0, 500)."""
    values = errors.dropna().to_numpy(dtype=float)
    if values.size == 0:
        return []
    low = math.floor(values.min() / bin_mw) * bin_mw
    high = math.floor(values.max() / bin_mw) * bin_mw + bin_mw
    edges = np.arange(low, high + bin_mw, bin_mw)
    counts, _ = np.histogram(values, bins=edges)
    return [
        {"from_mw": int(edges[i]), "to_mw": int(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]


# ---------------------------------------------------------------- endpoints


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    manifest = json.loads((analysis.DATA_DIR / "manifest.json").read_text())
    return {
        "first_decision_date": FIRST_DECISION_DATE.isoformat(),
        "last_decision_date": LAST_DECISION_DATE.isoformat(),
        "default_cutoff": analysis.DEFAULT_CUTOFF.strftime("%H:%M"),
        "cutoff_note": "Demo assumption, not a market rule. Times are Europe/London.",
        "timezone": "Europe/London",
        "error_convention": "error = forecast - actual (MW); positive = over-forecast",
        "alignment_note": (
            "Forecasts are hourly; actuals are half-hourly. Each hour's actual is the mean "
            "of its two half-hours, and is missing if either half-hour is missing."
        ),
        "selection_rule": (
            "For each delivery hour, the forecast with the latest publish time at or "
            "before the decision cutoff. Actuals are never used to choose forecasts."
        ),
        "data_retrieved_at_utc": manifest.get("generated_at_utc"),
        "source": manifest.get("source", {}).get("base_url"),
        "attribution": manifest.get("source", {}).get("attribution"),
        "licence_url": manifest.get("source", {}).get("licence"),
    }


@app.get("/api/decision")
def decision(
    date_: str = Query(..., alias="date", description="Decision date, YYYY-MM-DD"),
    cutoff: str = Query(analysis.DEFAULT_CUTOFF.strftime("%H:%M"), description="HH:MM, Europe/London"),
) -> dict:
    d = parse_decision_date(date_)
    cut = parse_cutoff_param(cutoff)
    actuals, forecasts = dataset()
    table = analysis.decision_table(actuals, forecasts, d, cut)

    hours = table.reset_index()
    half_hours = actuals[
        (actuals["start_time"] >= table.index[0])
        & (actuals["start_time"] < table.index[-1] + pd.Timedelta(hours=1))
    ]
    publish_times = sorted(table["publish_time"].dropna().unique())
    return {
        "decision_date": d.isoformat(),
        "delivery_date": analysis.delivery_date(d).isoformat(),
        "cutoff_local": cut.strftime("%H:%M"),
        "cutoff_utc": clean(analysis.cutoff_datetime(d, cut)),
        "publish_times_used": [clean(pd.Timestamp(t)) for t in publish_times],
        "coverage": clean_dict(analysis.coverage(table)),
        "metrics": clean_dict(analysis.error_metrics(table["error_mw"])),
        "hours": records(hours),
        "actuals_half_hourly": records(half_hours),
    }


@app.get("/api/accuracy")
def accuracy(
    cutoff: str = Query(analysis.DEFAULT_CUTOFF.strftime("%H:%M"), description="HH:MM, Europe/London"),
) -> dict:
    cut = parse_cutoff_param(cutoff)
    actuals, forecasts = dataset()
    result = analysis.accuracy(actuals, forecasts, decision_dates(), cut)
    return {
        "cutoff_local": cut.strftime("%H:%M"),
        "overall": clean_dict(result["overall"]),
        "days": records(result["days"]),
        "error_histogram": histogram(result["hours"]["error_mw"]),
        "histogram_bin_mw": HISTOGRAM_BIN_MW,
    }


# Mounted last so every /api route above takes priority over static files.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
