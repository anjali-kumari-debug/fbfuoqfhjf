"""FastAPI routes over the processed Elexon data, plus the built React app.

Run from backend/:  ../.venv/bin/uvicorn app.main:app --reload --port 8001
Interactive docs:   http://127.0.0.1:8001/docs

This module only validates input, calls app.analysis and shapes JSON.
Forecast selection, alignment and metrics live in app.analysis.

The processed data is loaded once at startup (never fetched from Elexon per
request). If it is missing, startup fails with instructions to create it.
If frontend/dist exists (after `npm run build`, or in Docker) it is served at "/".
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from . import analysis
from .serialize import clean, clean_dict, records

FRONTEND_DIST = Path(
    os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist")
)
FIRST_DECISION_DATE = date(2026, 1, 1)
LAST_DECISION_DATE = date(2026, 1, 31)
HISTOGRAM_BIN_MW = 500
REQUIRED_FILES = ("actuals.csv", "forecasts.csv", "manifest.json")

TIMEZONE = "Europe/London"
ERROR_DEFINITION = "error = forecast - actual (MW); positive = over-forecast, negative = under-forecast"
DECISION_TIME_NOTE = (
    "Decision time is a demo assumption, not a market rule. It is a Europe/London local time on each "
    "decision date; only forecasts published at or before it are eligible."
)
ALIGNMENT_NOTE = (
    "Forecasts are hourly; actuals are half-hourly. Each hour's actual is the mean of its two half-hours, "
    "and is missing if either half-hour is missing."
)
SELECTION_RULE = (
    "For each delivery hour, the forecast with the latest publish time at or before the decision cutoff. "
    "Actuals are never used to choose forecasts."
)


# ---------------------------------------------------------------- data loading


class DataUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Dataset:
    actuals: pd.DataFrame
    forecasts: pd.DataFrame
    manifest: dict


def data_dir() -> Path:
    return Path(os.environ.get("WIND_DATA_DIR", analysis.DATA_DIR))


def load_dataset(directory: Path) -> Dataset:
    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise DataUnavailableError(
            f"Required data files are missing from {directory}: {', '.join(missing)}.\n"
            "Create them from the repository root with:\n"
            "    python -m backend.app.fetch_data --decision-month 2026-01\n"
            "(or set WIND_DATA_DIR to a folder that contains them)."
        )
    actuals, forecasts = analysis.load_data(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    return Dataset(actuals, forecasts, manifest)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.dataset = load_dataset(data_dir())  # once, at startup
    yield


app = FastAPI(title="Wind forecast accuracy API", version="2.0.0", lifespan=lifespan)


def dataset(request: Request) -> Dataset:
    return request.app.state.dataset


# ---------------------------------------------------------------- input checks (422 = client error)


def parse_decision_time(text: str) -> time:
    try:
        return analysis.parse_cutoff(text)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"decision_time must be HH:MM (24-hour, 00:00 to 23:59), got {text!r}"
        ) from None


def parse_decision_date(text: str, name: str) -> date:
    try:
        d = date.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be a date in YYYY-MM-DD format, got {text!r}") from None
    if not FIRST_DECISION_DATE <= d <= LAST_DECISION_DATE:
        raise HTTPException(
            status_code=422,
            detail=f"{name} must be a decision date between {FIRST_DECISION_DATE} and {LAST_DECISION_DATE}, got {d}",
        )
    return d


def cutoff_info(d: date, cut: time) -> dict:
    cutoff_utc = analysis.cutoff_datetime(d, cut)
    return {
        "decision_cutoff": cutoff_utc.tz_convert(TIMEZONE).isoformat(),  # local time with UTC offset
        "decision_cutoff_utc": clean(cutoff_utc),
        "timezone": TIMEZONE,
    }


# ---------------------------------------------------------------- endpoints


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta(request: Request) -> dict:
    manifest = dataset(request).manifest
    source = manifest.get("source", {})
    return {
        "first_decision_date": FIRST_DECISION_DATE.isoformat(),
        "last_decision_date": LAST_DECISION_DATE.isoformat(),
        "default_decision_time": analysis.DEFAULT_CUTOFF.strftime("%H:%M"),
        "decision_time_note": DECISION_TIME_NOTE,
        "timezone": TIMEZONE,
        "error_definition": ERROR_DEFINITION,
        "alignment_note": ALIGNMENT_NOTE,
        "selection_rule": SELECTION_RULE,
        "data_retrieved_at_utc": manifest.get("generated_at_utc"),
        "source": source.get("base_url"),
        "attribution": source.get("attribution"),
        "licence_url": source.get("licence"),
    }


@app.get("/api/forecast")
def forecast(
    request: Request,
    decision_date: str = Query(..., description="Decision date, YYYY-MM-DD (January 2026)"),
    decision_time: str = Query(analysis.DEFAULT_CUTOFF.strftime("%H:%M"), description="HH:MM, Europe/London"),
) -> dict:
    d = parse_decision_date(decision_date, "decision_date")
    cut = parse_decision_time(decision_time)
    data = dataset(request)
    table = analysis.decision_table(data.actuals, data.forecasts, d, cut)

    intervals = (
        table.reset_index()
        .rename(columns={"start_time": "target_time", "publish_time": "forecast_publish_time"})
        [["target_time", "forecast_mw", "forecast_publish_time", "actual_mw", "error_mw", "lead_time_hours"]]
    )
    first, last = table.index[0], table.index[-1] + pd.Timedelta(hours=1)
    half_hours = data.actuals[(data.actuals["start_time"] >= first) & (data.actuals["start_time"] < last)]
    return {
        "decision_date": d.isoformat(),
        "delivery_date": analysis.delivery_date(d).isoformat(),
        "decision_time": cut.strftime("%H:%M"),
        **cutoff_info(d, cut),
        "decision_time_note": DECISION_TIME_NOTE,
        "error_definition": ERROR_DEFINITION,
        "publish_times_used": [clean(pd.Timestamp(t)) for t in sorted(table["publish_time"].dropna().unique())],
        "coverage": clean_dict(analysis.coverage(table)),
        "metrics": clean_dict(analysis.error_metrics(table["error_mw"])),
        "intervals": records(intervals),
        "actuals_half_hourly": records(half_hours[["start_time", "generation_mw"]]),
    }


@app.get("/api/accuracy")
def accuracy(
    request: Request,
    start_date: str = Query(FIRST_DECISION_DATE.isoformat(), description="First decision date, YYYY-MM-DD"),
    end_date: str = Query(LAST_DECISION_DATE.isoformat(), description="Last decision date, YYYY-MM-DD"),
    decision_time: str = Query(analysis.DEFAULT_CUTOFF.strftime("%H:%M"), description="HH:MM, Europe/London"),
) -> dict:
    start = parse_decision_date(start_date, "start_date")
    end = parse_decision_date(end_date, "end_date")
    if start > end:
        raise HTTPException(status_code=422, detail=f"start_date ({start}) must be on or before end_date ({end})")
    cut = parse_decision_time(decision_time)
    data = dataset(request)

    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    # Each decision date uses its own cutoff and its own next-day delivery intervals.
    result = analysis.accuracy(data.actuals, data.forecasts, dates, cut)
    days = result["days"].copy()
    days["decision_cutoff"] = [cutoff_info(d, cut)["decision_cutoff"] for d in days["decision_date"]]
    intervals = (
        result["hours"]
        .reset_index()
        .rename(columns={"start_time": "target_time", "publish_time": "forecast_publish_time"})
        [["target_time", "decision_date", "forecast_mw", "forecast_publish_time", "actual_mw", "error_mw"]]
    )
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "decision_count": len(dates),
        "decision_time": cut.strftime("%H:%M"),
        "timezone": TIMEZONE,
        "decision_time_note": DECISION_TIME_NOTE,
        "error_definition": ERROR_DEFINITION,
        "pooled": clean_dict(result["overall"]),
        "days": records(days),
        "intervals": records(intervals),  # hourly selected forecast vs retrospective actual
        "error_histogram": analysis.error_histogram(result["hours"]["error_mw"], HISTOGRAM_BIN_MW),
        "histogram_bin_mw": HISTOGRAM_BIN_MW,
    }


# Mounted last so every /api route above takes priority over static files.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
