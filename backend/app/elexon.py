"""Elexon API access and cleaning for wind actuals (FUELHH) and forecasts (WINDFOR).

Verified API details are in docs/data-notes.md. Principles:
- Requests are bounded (7-day chunks), time out, and retry a bounded number of times.
- Original response bodies are returned untouched so callers can preserve them.
- Cleaning never fabricates values. Invalid or missing values become NaN and are
  counted. Rows are removed only when they cannot be placed in time, and every
  removal is counted in the report.
- Exact duplicates are removed. Conflicting duplicates are reported; a value is
  kept only when there is a principled rule (a later revision of an actual),
  otherwise it is set to missing.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
FUELHH_PATH = "/datasets/FUELHH/stream"
WINDFOR_PATH = "/datasets/WINDFOR/stream"

CHUNK_DAYS = 7  # no documented limit; 35 days worked in one request, 7 keeps requests small
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 4  # 1 try + up to 3 retries
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 30
MAX_CONFLICTS_LISTED = 50


# ---------------------------------------------------------------- HTTP


@dataclass
class Response:
    """One API response, kept exactly as received."""

    dataset: str
    url: str
    params: dict
    status: int
    body: bytes
    retrieved_at_utc: str
    attempts: int

    def rows(self) -> list[dict]:
        data = httpx.Response(self.status, content=self.body).json()
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list from {self.url}, got {type(data).__name__}")
        return data


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS)


def get_with_retries(
    client: httpx.Client, dataset: str, path: str, params: dict, sleep=_time.sleep
) -> Response:
    """GET with bounded retries on timeouts, connection errors, 429 and 5xx.

    Waits 1, 2, 4... seconds between attempts (or the server's Retry-After),
    capped at MAX_BACKOFF_SECONDS. Other errors (e.g. 400) fail immediately.
    """
    url = f"{BASE_URL}{path}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(min(2 ** (attempt - 1), MAX_BACKOFF_SECONDS))
            continue
        if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
            retry_after = response.headers.get("Retry-After", "")
            wait = float(retry_after) if retry_after.isdigit() else 2 ** (attempt - 1)
            sleep(min(wait, MAX_BACKOFF_SECONDS))
            continue
        response.raise_for_status()
        return Response(
            dataset=dataset,
            url=str(response.request.url),
            params=params,
            status=response.status_code,
            body=response.content,
            retrieved_at_utc=_utc_iso(pd.Timestamp.now(tz="UTC")),
            attempts=attempt,
        )
    raise RuntimeError("unreachable")  # pragma: no cover


def fetch_fuelhh_wind(client: httpx.Client, first: date, last: date, sleep=_time.sleep) -> list[Response]:
    """WIND actuals for settlement dates first..last (inclusive), one response per chunk."""
    responses = []
    chunk_start = first
    while chunk_start <= last:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), last)
        params = {
            "settlementDateFrom": chunk_start.isoformat(),
            "settlementDateTo": chunk_end.isoformat(),
            "fuelType": "WIND",
        }
        responses.append(get_with_retries(client, "FUELHH", FUELHH_PATH, params, sleep))
        chunk_start = chunk_end + timedelta(days=1)
    return responses


def fetch_windfor(client: httpx.Client, start: datetime, end: datetime, sleep=_time.sleep) -> list[Response]:
    """WINDFOR publications with publishTime in [start, end], one response per chunk.

    The API filters on publish time only, so every historical publication in the
    range is returned, including ones published before the decision month.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    responses = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        params = {"publishDateTimeFrom": _utc_iso(chunk_start), "publishDateTimeTo": _utc_iso(chunk_end)}
        responses.append(get_with_retries(client, "WINDFOR", WINDFOR_PATH, params, sleep))
        chunk_start = chunk_end
    return responses


# ---------------------------------------------------------------- cleaning helpers


def _utc_iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(series: pd.Series) -> pd.Series:
    """Parse timestamps as tz-aware UTC. Missing or unparseable values become NaT."""
    return pd.to_datetime(series, utc=True, format="ISO8601", errors="coerce")


def _validate_generation(raw: pd.Series, report: dict) -> pd.Series:
    """Numeric MW values. Non-numeric or non-finite become NaN (counted); negatives are flagged."""
    values = pd.to_numeric(raw, errors="coerce").astype(float)
    report["generation_null"] = int(raw.isna().sum())
    report["generation_not_numeric"] = int((raw.notna() & values.isna()).sum())
    infinite = np.isinf(values)
    report["generation_not_finite"] = int(infinite.sum())
    values[infinite] = np.nan
    report["generation_negative"] = int((values < 0).sum())  # kept, but reported
    return values


def _conflict_examples(conflicts: pd.DataFrame, key: list[str]) -> list[dict]:
    examples = []
    for values, group in conflicts.groupby(key, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        examples.append(
            {
                **{k: (_utc_iso(v) if isinstance(v, pd.Timestamp) else v) for k, v in zip(key, values)},
                "rows": [
                    {k: (None if pd.isna(v) else _utc_iso(v) if isinstance(v, pd.Timestamp) else v) for k, v in r.items()}
                    for r in group.drop(columns=key).to_dict("records")
                ],
            }
        )
        if len(examples) >= MAX_CONFLICTS_LISTED:
            break
    return examples


# ---------------------------------------------------------------- cleaning


def clean_actuals(rows: list[dict], window_start: datetime, window_end: datetime) -> tuple[pd.DataFrame, dict]:
    """Normalised WIND actuals with start_time in [window_start, window_end).

    Output columns: start_time, generation_mw, publish_time, settlement_date,
    settlement_period. Timestamps are tz-aware UTC.

    Duplicates: exact copies are removed. Rows with the same start_time but a
    different value are conflicts. If they have different publish times, the
    latest publication is a revision and is kept. Otherwise there is no basis to
    choose, so the value is set to missing. All conflicts are reported.
    """
    columns = ["startTime", "publishTime", "settlementDate", "settlementPeriod", "fuelType", "generation"]
    report: dict = {"raw_rows": len(rows)}
    df = pd.DataFrame(rows, columns=columns)

    before = len(df)
    df = df.drop_duplicates()
    report["exact_duplicates_removed"] = before - len(df)

    df = df[df["fuelType"] == "WIND"]
    report["non_wind_rows_removed"] = report["raw_rows"] - report["exact_duplicates_removed"] - len(df)

    out = pd.DataFrame(
        {
            "start_time": _parse_utc(df["startTime"]),
            "publish_time": _parse_utc(df["publishTime"]),
            "settlement_date": df["settlementDate"],
            "settlement_period": pd.to_numeric(df["settlementPeriod"], errors="coerce").astype("Int64"),
        }
    )
    out["generation_mw"] = _validate_generation(df["generation"], report)

    invalid_start = out["start_time"].isna()
    report["rows_without_valid_start_time_removed"] = int(invalid_start.sum())
    out = out[~invalid_start]
    report["rows_without_valid_publish_time"] = int(out["publish_time"].isna().sum())

    off_grid = (out["start_time"].dt.minute % 30 != 0) | (out["start_time"].dt.second != 0)
    report["rows_off_half_hour_grid_removed"] = int(off_grid.sum())
    out = out[~off_grid]

    out, conflict_report = _resolve_actual_conflicts(out)
    report |= conflict_report

    out = out[(out["start_time"] >= window_start) & (out["start_time"] < window_end)]
    out = out.sort_values("start_time").reset_index(drop=True)
    report["rows"] = len(out)
    report["missing_generation_values"] = int(out["generation_mw"].isna().sum())
    report["settlement_fields_inconsistent"] = int(_settlement_mismatches(out).sum())
    return out[["start_time", "generation_mw", "publish_time", "settlement_date", "settlement_period"]], report


def _resolve_actual_conflicts(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    dup = df["start_time"].duplicated(keep=False)
    groups = df[dup]
    values_per_key = groups.groupby("start_time")["generation_mw"].nunique(dropna=False)
    conflicts = groups[groups["start_time"].isin(values_per_key[values_per_key > 1].index)]
    report = {"conflicting_start_times": int(conflicts["start_time"].nunique())}

    resolved = []
    revisions = unresolved = 0
    for start, group in groups.groupby("start_time"):
        if group["generation_mw"].nunique(dropna=False) <= 1:
            # Same value repeated (e.g. republished): not a conflict, keep the latest copy.
            resolved.append(group.sort_values("publish_time", na_position="first").iloc[[-1]])
            continue
        known = group.dropna(subset=["publish_time"])
        if len(known) and known["publish_time"].nunique() == len(known) and len(known) == len(group):
            resolved.append(known.sort_values("publish_time").iloc[[-1]])  # latest revision wins
            revisions += 1
        else:
            row = group.iloc[[0]].copy()
            row["generation_mw"] = np.nan  # no principled choice: keep the interval, mark missing
            resolved.append(row)
            unresolved += 1
    report["conflicts_resolved_as_latest_revision"] = revisions
    report["conflicts_set_to_missing"] = unresolved
    report["conflict_examples"] = _conflict_examples(conflicts, ["start_time"])
    combined = pd.concat([df[~dup], *resolved]) if resolved else df[~dup]
    return combined, report


def _settlement_mismatches(df: pd.DataFrame) -> pd.Series:
    """Rows whose settlement date/period disagree with start_time (Europe/London day)."""
    local = df["start_time"].dt.tz_convert("Europe/London")
    day_start = local.dt.normalize()  # London midnight (tz-aware)
    period = ((df["start_time"] - day_start.dt.tz_convert("UTC")).dt.total_seconds() // 1800 + 1).astype("Int64")
    same_date = local.dt.strftime("%Y-%m-%d") == df["settlement_date"].astype(str)
    return ~(same_date & (period == df["settlement_period"]).fillna(False))


def clean_forecasts(rows: list[dict], window_start: datetime, window_end: datetime) -> tuple[pd.DataFrame, dict]:
    """Normalised WINDFOR history: every publication with a target hour in the window.

    Output columns: publish_time, start_time, generation_mw (tz-aware UTC).
    Filtering is on start_time only, so publications from before the decision
    month are kept. Exact duplicates are removed. Conflicting values for the same
    (publish_time, start_time) have no principled winner, so they are set to
    missing and reported.
    """
    report: dict = {"raw_rows": len(rows)}
    df = pd.DataFrame(rows, columns=["publishTime", "startTime", "generation"])

    before = len(df)
    df = df.drop_duplicates()
    report["exact_duplicates_removed"] = before - len(df)

    out = pd.DataFrame({"publish_time": _parse_utc(df["publishTime"]), "start_time": _parse_utc(df["startTime"])})
    out["generation_mw"] = _validate_generation(df["generation"], report)

    no_time = out["publish_time"].isna() | out["start_time"].isna()
    report["rows_without_valid_timestamps_removed"] = int(no_time.sum())
    out = out[~no_time]

    off_grid = (out["start_time"].dt.minute != 0) | (out["start_time"].dt.second != 0)
    report["rows_off_hour_grid_removed"] = int(off_grid.sum())
    out = out[~off_grid]

    key = ["publish_time", "start_time"]
    dup = out.duplicated(key, keep=False)
    conflicts = out[dup]
    report["conflicting_keys_set_to_missing"] = int(conflicts.groupby(key).ngroups) if len(conflicts) else 0
    report["conflict_examples"] = _conflict_examples(conflicts, key)
    if len(conflicts):
        merged = conflicts.drop_duplicates(key).copy()
        merged["generation_mw"] = np.nan
        out = pd.concat([out[~dup], merged])

    out = out[(out["start_time"] >= window_start) & (out["start_time"] < window_end)]
    out = out.sort_values(key).reset_index(drop=True)
    report["rows"] = len(out)
    report["publications"] = int(out["publish_time"].nunique())
    report["earliest_publication"] = _utc_iso(out["publish_time"].min()) if len(out) else None
    report["missing_generation_values"] = int(out["generation_mw"].isna().sum())
    return out[["publish_time", "start_time", "generation_mw"]], report


def to_csv_utc(df: pd.DataFrame, path) -> None:
    """Write a frame with timestamps as ISO-8601 UTC strings ending in 'Z'."""
    out = df.copy()
    for col in out.columns:
        if isinstance(out[col].dtype, pd.DatetimeTZDtype):
            out[col] = out[col].dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif pd.api.types.is_float_dtype(out[col]):
            values = out[col].dropna()
            if (values == values.round()).all():
                out[col] = out[col].astype("Int64")  # whole MW stay integers; missing stays empty
    out.to_csv(path, index=False)
