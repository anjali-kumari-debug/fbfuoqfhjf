"""Pipeline tests against a fake Elexon API (httpx.MockTransport): no network needed."""

import hashlib
import json
from datetime import date

import httpx
import pandas as pd
import pytest

from app import elexon, fetch_data


# ------------------------------------------------------------ date planning


def test_plan_for_january_2026_matches_the_next_day_delivery_rules():
    plan = fetch_data.plan_for_month("2026-01")
    assert plan.decision_dates[0] == date(2026, 1, 1)
    assert plan.decision_dates[-1] == date(2026, 1, 31)
    assert plan.delivery_start.isoformat() == "2026-01-02T00:00:00+00:00"
    assert plan.delivery_end.isoformat() == "2026-02-02T00:00:00+00:00"  # includes all of 1 Feb
    assert plan.publish_start.date() == date(2025, 12, 28)  # before January, for the first decision
    assert plan.publish_end.isoformat() == "2026-02-01T00:00:00+00:00"  # end of the last decision date
    assert (plan.settlement_first, plan.settlement_last) == (date(2026, 1, 1), date(2026, 2, 2))


def test_plan_handles_year_end():
    plan = fetch_data.plan_for_month("2026-12")
    assert plan.decision_dates[-1] == date(2026, 12, 31)
    assert plan.delivery_end.date() == date(2027, 1, 2)


@pytest.mark.parametrize("month", ["2026-1", "2026-13", "January", ""])
def test_plan_rejects_bad_month(month):
    with pytest.raises(ValueError):
        fetch_data.plan_for_month(month)


# ------------------------------------------------------------ retries


def client_with(responses):
    """A client whose transport returns the given responses (or raises exceptions) in order."""
    calls = []

    def handler(request):
        calls.append(request)
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def no_sleep(_seconds):
    pass


def test_retries_on_server_errors_then_succeeds():
    client, calls = client_with([httpx.Response(503), httpx.Response(429), httpx.Response(200, json=[])])
    response = elexon.get_with_retries(client, "WINDFOR", elexon.WINDFOR_PATH, {}, sleep=no_sleep)
    assert response.status == 200 and response.attempts == 3 and len(calls) == 3


def test_retries_on_timeout():
    client, calls = client_with([httpx.ReadTimeout("slow"), httpx.Response(200, json=[])])
    assert elexon.get_with_retries(client, "WINDFOR", elexon.WINDFOR_PATH, {}, sleep=no_sleep).attempts == 2


def test_retries_are_bounded():
    client, calls = client_with([httpx.Response(503)])
    with pytest.raises(httpx.HTTPStatusError):
        elexon.get_with_retries(client, "WINDFOR", elexon.WINDFOR_PATH, {}, sleep=no_sleep)
    assert len(calls) == elexon.MAX_ATTEMPTS


def test_client_errors_are_not_retried():
    client, calls = client_with([httpx.Response(400, json={"error": "bad"})])
    with pytest.raises(httpx.HTTPStatusError):
        elexon.get_with_retries(client, "WINDFOR", elexon.WINDFOR_PATH, {}, sleep=no_sleep)
    assert len(calls) == 1


def test_waits_grow_between_attempts_and_are_capped():
    waits = []
    client, _ = client_with([httpx.Response(503), httpx.Response(503), httpx.Response(200, json=[])])
    elexon.get_with_retries(client, "WINDFOR", elexon.WINDFOR_PATH, {}, sleep=waits.append)
    assert waits == [1, 2]
    client, _ = client_with([httpx.Response(429, headers={"Retry-After": "999"}), httpx.Response(200, json=[])])
    elexon.get_with_retries(client, "WINDFOR", elexon.WINDFOR_PATH, {}, sleep=(waits := []).append)
    assert waits == [elexon.MAX_BACKOFF_SECONDS]


# ------------------------------------------------------------ end-to-end with a fake API


def fake_elexon(request):
    """FUELHH: one WIND row at 00:00 UTC for each settlement date. WINDFOR: one publication
    per request, published at the chunk start, forecasting 2 Jan 00:00 and 01:00."""
    q = request.url.params
    if request.url.path.endswith("/FUELHH/stream"):
        days = pd.date_range(q["settlementDateFrom"], q["settlementDateTo"], freq="D")
        rows = [
            {
                "dataset": "FUELHH",
                "publishTime": f"{d:%Y-%m-%d}T00:30:00Z",
                "startTime": f"{d:%Y-%m-%d}T00:00:00Z",
                "settlementDate": f"{d:%Y-%m-%d}",
                "settlementPeriod": 1,
                "fuelType": "WIND",
                "generation": 1000,
            }
            for d in days
        ]
    else:
        published = q["publishDateTimeFrom"]
        rows = [
            {"dataset": "WINDFOR", "publishTime": published, "startTime": "2026-01-02T00:00:00Z", "generation": 1100},
            {"dataset": "WINDFOR", "publishTime": published, "startTime": "2026-01-02T01:00:00Z", "generation": 1200},
        ]
    return httpx.Response(200, content=json.dumps(rows).encode())


@pytest.fixture
def pipeline_run(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(fake_elexon))
    plan = fetch_data.plan_for_month("2026-01")
    manifest = fetch_data.run(plan, raw_root=tmp_path / "raw", processed_dir=tmp_path / "processed", client=client)
    return manifest, tmp_path


def test_raw_responses_are_preserved_byte_for_byte(pipeline_run, monkeypatch):
    manifest, tmp_path = pipeline_run
    assert len(manifest["requests"]) == 10  # 5 FUELHH + 5 WINDFOR chunks of at most 7 days
    for entry in manifest["requests"]:
        body = (tmp_path / "raw" / "2026-01" / entry["raw_file"].split("/")[-1]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry["sha256"]


def test_requests_are_bounded_chunks(pipeline_run):
    manifest, _ = pipeline_run
    for entry in manifest["requests"]:
        p = entry["params"]
        if entry["dataset"] == "FUELHH":
            days = (date.fromisoformat(p["settlementDateTo"]) - date.fromisoformat(p["settlementDateFrom"])).days + 1
        else:
            days = (pd.Timestamp(p["publishDateTimeTo"]) - pd.Timestamp(p["publishDateTimeFrom"])).days
        assert days <= elexon.CHUNK_DAYS


def test_processed_files_and_manifest_are_written(pipeline_run):
    manifest, tmp_path = pipeline_run
    actuals = pd.read_csv(tmp_path / "processed" / "actuals.csv")
    assert actuals["start_time"].str.endswith("Z").all()
    assert manifest["row_counts"]["actuals_processed"] == 31  # one half-hour per delivery day
    for key in ("source", "request_ranges", "requests", "row_counts", "cleaning", "coverage", "assumptions"):
        assert manifest[key]
    assert "Elexon" in manifest["source"]["attribution"]
    assert all(r["retrieved_at_utc"].endswith("Z") for r in manifest["requests"])


def test_coverage_reports_gaps_instead_of_filling_them(pipeline_run):
    manifest, tmp_path = pipeline_run
    cov = manifest["coverage"]
    assert cov["actuals"]["expected_half_hours"] == 31 * 48
    assert cov["actuals"]["present_half_hours"] == 31  # the fake API only has 00:00 rows
    assert len(cov["actuals"]["missing_half_hours"]) == 31 * 47
    assert cov["forecasts"]["hours_with_any_forecast"] == 2
    actuals = pd.read_csv(tmp_path / "processed" / "actuals.csv")
    assert len(actuals) == 31  # nothing fabricated for the missing half-hours
