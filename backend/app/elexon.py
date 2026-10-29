"""Download and clean Elexon wind data.

- Actuals: FUELHH stream, WIND only, 30-minute resolution.
- Forecasts: WINDFOR stream, hourly, one set of rows per publication.

Timestamps stay timezone-aware in UTC. Callers decide day boundaries in
Europe/London. Missing or invalid generation values are kept as NaN, never
filled or dropped. See docs/data-notes.md for the API findings.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx
import pandas as pd

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
CHUNK_DAYS = 7  # a 7-day request was verified to work; keep requests that size


def make_client() -> httpx.Client:
    """HTTP client with a timeout and retries on connection errors."""
    return httpx.Client(timeout=60, transport=httpx.HTTPTransport(retries=3))


def _get_list(client: httpx.Client, path: str, params: dict) -> list[dict]:
    response = client.get(f"{BASE_URL}{path}", params=params)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list from {path}, got {type(data).__name__}")
    return data


def fetch_fuelhh_wind(client: httpx.Client, first: date, last: date) -> list[dict]:
    """WIND actuals for settlement dates first..last (inclusive), in 7-day chunks."""
    rows: list[dict] = []
    chunk_start = first
    while chunk_start <= last:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), last)
        rows += _get_list(
            client,
            "/datasets/FUELHH/stream",
            {
                "settlementDateFrom": chunk_start.isoformat(),
                "settlementDateTo": chunk_end.isoformat(),
                "fuelType": "WIND",
            },
        )
        chunk_start = chunk_end + timedelta(days=1)
    return rows


def fetch_windfor(client: httpx.Client, start: datetime, end: datetime) -> list[dict]:
    """All WINDFOR rows with publishTime in [start, end), in 7-day chunks.

    The API filter may include both ends, so duplicates are possible at chunk
    boundaries. clean_forecasts() removes them.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    rows: list[dict] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        rows += _get_list(
            client,
            "/datasets/WINDFOR/stream",
            {
                "publishDateTimeFrom": _utc_iso(chunk_start),
                "publishDateTimeTo": _utc_iso(chunk_end),
            },
        )
        chunk_start = chunk_end
    return rows


def _utc_iso(ts: datetime) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(series: pd.Series) -> pd.Series:
    """Parse API timestamps (e.g. '2026-01-01T00:00:00Z') as tz-aware UTC."""
    return pd.to_datetime(series, utc=True, format="ISO8601")


def clean_actuals(rows: list[dict], window_start: datetime, window_end: datetime) -> tuple[pd.DataFrame, dict]:
    """Cleaned WIND actuals with start_time in [window_start, window_end).

    Returns (frame with columns start_time, generation_mw, report dict).
    If one startTime appears more than once, the row with the latest
    publishTime wins (it is the most recent revision).
    """
    report = {"raw_rows": len(rows)}
    df = pd.DataFrame(rows, columns=["startTime", "publishTime", "fuelType", "generation"])
    df = df[df["fuelType"] == "WIND"]
    report["non_wind_rows_removed"] = report["raw_rows"] - len(df)

    df = pd.DataFrame(
        {
            "start_time": _parse_utc(df["startTime"]),
            "publish_time": _parse_utc(df["publishTime"]),
            "generation_mw": pd.to_numeric(df["generation"], errors="coerce"),
        }
    )
    # The API schema allows null timestamps. A row without startTime cannot be
    # placed in time, so it is removed, but counted rather than dropped silently.
    no_start = df["start_time"].isna()
    report["rows_without_start_time_removed"] = int(no_start.sum())
    df = df[~no_start]

    # A missing publishTime sorts first, so it never beats a known revision.
    df = df.sort_values(["start_time", "publish_time"], na_position="first")
    before = len(df)
    df = df.drop_duplicates("start_time", keep="last")
    report["duplicate_start_times_removed"] = before - len(df)

    df = df[(df["start_time"] >= window_start) & (df["start_time"] < window_end)]
    df = df[["start_time", "generation_mw"]].reset_index(drop=True)
    report["rows"] = len(df)
    report["missing_generation_values"] = int(df["generation_mw"].isna().sum())
    return df, report


def clean_forecasts(rows: list[dict], window_start: datetime, window_end: datetime) -> tuple[pd.DataFrame, dict]:
    """Cleaned WINDFOR rows whose start_time is in [window_start, window_end).

    Every publication is kept, so any cutoff can be applied later.
    Returns (frame with columns publish_time, start_time, generation_mw, report).
    """
    report = {"raw_rows": len(rows)}
    df = pd.DataFrame(rows, columns=["publishTime", "startTime", "generation"])
    df = pd.DataFrame(
        {
            "publish_time": _parse_utc(df["publishTime"]),
            "start_time": _parse_utc(df["startTime"]),
            "generation_mw": pd.to_numeric(df["generation"], errors="coerce"),
        }
    )
    # Without publishTime the no-look-ahead rule cannot be applied, and without
    # startTime the row has no target hour: remove such rows, but count them.
    no_time = df["publish_time"].isna() | df["start_time"].isna()
    report["rows_without_timestamps_removed"] = int(no_time.sum())
    df = df[~no_time]

    before = len(df)
    df = df.drop_duplicates(["publish_time", "start_time"], keep="last")
    report["duplicate_rows_removed"] = before - len(df)

    df = df[(df["start_time"] >= window_start) & (df["start_time"] < window_end)]
    df = df.sort_values(["publish_time", "start_time"]).reset_index(drop=True)
    report["rows"] = len(df)
    report["publications"] = int(df["publish_time"].nunique())
    report["missing_generation_values"] = int(df["generation_mw"].isna().sum())
    return df, report


def to_csv_utc(df: pd.DataFrame, path) -> None:
    """Write a frame with timestamps as ISO-8601 UTC strings ending in 'Z'."""
    out = df.copy()
    for col in out.columns:
        if isinstance(out[col].dtype, pd.DatetimeTZDtype):
            out[col] = out[col].dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(path, index=False)
