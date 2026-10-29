import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def strict_json(response):
    """Parse JSON rejecting NaN/Infinity, which browsers cannot parse."""
    def reject(token):
        raise ValueError(f"invalid JSON number {token}")

    return json.loads(response.text, parse_constant=reject)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_meta_labels_cutoff_as_demo_assumption():
    body = client.get("/api/meta").json()
    assert body["default_cutoff"] == "10:00"
    assert "demo assumption" in body["cutoff_note"].lower()
    assert body["first_decision_date"] == "2026-01-01"
    assert body["last_decision_date"] == "2026-01-31"


def test_decision_uses_default_cutoff_and_next_london_day():
    response = client.get("/api/decision", params={"date": "2026-01-15"})
    assert response.status_code == 200
    body = strict_json(response)
    assert body["delivery_date"] == "2026-01-16"
    assert body["cutoff_local"] == "10:00"
    assert len(body["hours"]) == 24
    assert len(body["actuals_half_hourly"]) == 48
    assert body["coverage"]["paired_coverage"] == 1.0
    assert all(p <= body["cutoff_utc"] for p in body["publish_times_used"])


def test_decision_hour_rows_have_expected_fields():
    body = client.get("/api/decision", params={"date": "2026-01-15"}).json()
    row = body["hours"][0]
    assert row["start_time"] == "2026-01-16T00:00:00Z"
    assert set(row) >= {"forecast_mw", "publish_time", "actual_mw", "error_mw", "lead_time_hours"}
    assert row["error_mw"] == pytest.approx(row["forecast_mw"] - row["actual_mw"])


def test_decision_31_january_is_scored_on_1_february():
    body = client.get("/api/decision", params={"date": "2026-01-31"}).json()
    assert body["delivery_date"] == "2026-02-01"
    assert body["coverage"]["paired_hours"] == 24


def test_missing_forecasts_are_null_not_zero():
    # At 00:00 on 1 Jan, only forecasts published by then are eligible.
    # Whatever is missing must come back as null, with valid JSON.
    response = client.get("/api/decision", params={"date": "2026-01-01", "cutoff": "00:00"})
    body = strict_json(response)
    for row in body["hours"]:
        if row["publish_time"] is None:
            assert row["forecast_mw"] is None and row["error_mw"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"date": "2026-02-01"},  # outside January
        {"date": "2025-12-31"},
        {"date": "15-01-2026"},  # wrong format
        {"date": "2026-01-15", "cutoff": "25:00"},
        {"date": "2026-01-15", "cutoff": "10am"},
        {},  # date is required
    ],
)
def test_decision_rejects_bad_input_with_422(params):
    assert client.get("/api/decision", params=params).status_code == 422


def test_accuracy_covers_all_january_decisions():
    response = client.get("/api/accuracy", params={"cutoff": "10:00"})
    assert response.status_code == 200
    body = strict_json(response)
    assert len(body["days"]) == 31
    assert body["overall"]["expected_hours"] == 744
    assert body["overall"]["n"] == 744
    assert sum(b["count"] for b in body["error_histogram"]) == 744


def test_accuracy_changes_with_cutoff():
    early = client.get("/api/accuracy", params={"cutoff": "06:00"}).json()["overall"]
    late = client.get("/api/accuracy", params={"cutoff": "16:00"}).json()["overall"]
    assert early["mae_mw"] != late["mae_mw"]


def test_accuracy_rejects_bad_cutoff():
    assert client.get("/api/accuracy", params={"cutoff": "9:00"}).status_code == 422
