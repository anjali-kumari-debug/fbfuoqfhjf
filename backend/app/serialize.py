"""Convert pandas/numpy values to JSON-safe Python values for API responses."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd


def utc_iso(ts: pd.Timestamp) -> str:
    return ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value):
    """NaN/NaT/NA -> None, timestamps -> UTC ISO strings, numpy -> Python numbers."""
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) else float(value)
    return value


def clean_dict(d: dict) -> dict:
    return {k: clean(v) for k, v in d.items()}


def records(df: pd.DataFrame) -> list[dict]:
    return [clean_dict(row) for row in df.to_dict("records")]
