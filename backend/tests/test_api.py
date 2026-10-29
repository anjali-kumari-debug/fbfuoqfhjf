import json
import math

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import FRONTEND_DIST, app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # `with` runs startup, which loads the data once
        yield c


def strict_json(response):
    """Parse JSON rejecting NaN/Infinity, which browsers cannot parse."""

    def reject(token):
        raise ValueError(f"invalid JSON number {token}")

    return json.loads(response.text, parse_constant=reject)


# ------------------------------------------------------------ health and startup


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_data_is_loaded_once_at_startup_not_per_request(client, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("data must not be reloaded per request")

    monkeypatch.setattr(main.analysis, "load_data", fail)
    monkeypatch.setattr(main, "load_dataset", fail)
    assert client.get("/api/forecast", params={"decision_date": "2026-01-10"}).status_code == 200
    assert client.get("/api/accuracy").status_code == 200


def test_startup_fails_clearly_when_data_files_are_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("WIND_DATA_DIR", str(tmp_path))
    with pytest.raises(main.DataUnavailableError) as excinfo:
        with TestClient(app):
            pass
    message = str(excinfo.value)
    assert "actuals.csv" in message and "manifest.json" in message
    assert "python -m backend.app.fetch_data --decision-month 2026-01" in message


def test_meta_labels_decision_time_as_demo_assumption(client):
    body = client.get("/api/meta").json()
    assert body["default_decision_time"] == "10:00"
    assert "demo assumption" in body["decision_time_note"].lower()
    assert body["first_decision_date"] == "2026-01-01"
    assert body["last_decision_date"] == "2026-01-31"
    assert "Elexon" in body["attribution"]


# ------------------------------------------------------------ /api/forecast


def test_forecast_returns_cutoff_with_timezone_and_next_day_delivery(client):
    response = client.get("/api/forecast", params={"decision_date": "2026-01-10", "decision_time": "10:00"})
    assert response.status_code == 200
    body = strict_json(response)
    assert body["decision_date"] == "2026-01-10"
    assert body["delivery_date"] == "2026-01-11"
    assert body["decision_cutoff"] == "2026-01-10T10:00:00+00:00"  # London local time with its offset
    assert body["decision_cutoff_utc"] == "2026-01-10T10:00:00Z"
    assert body["timezone"] == "Europe/London"
    assert "forecast - actual" in body["error_definition"]


def test_forecast_intervals_have_every_required_field(client):
    body = client.get("/api/forecast", params={"decision_date": "2026-01-10"}).json()
    assert len(body["intervals"]) == 24
    first = body["intervals"][0]
    assert first["target_time"] == "2026-01-11T00:00:00Z"
    for key in ("forecast_mw", "forecast_publish_time", "actual_mw", "error_mw"):
        assert key in first
    assert first["error_mw"] == pytest.approx(first["forecast_mw"] - first["actual_mw"])
    assert all(p <= body["decision_cutoff_utc"] for p in body["publish_times_used"])
    assert all(i["forecast_publish_time"] <= body["decision_cutoff_utc"] for i in body["intervals"])


def test_forecast_coverage_reports_counts_separately(client):
    coverage = client.get("/api/forecast", params={"decision_date": "2026-01-10"}).json()["coverage"]
    assert coverage == {
        "expected_intervals": 24,
        "forecast_intervals": 24,
        "actual_intervals": 24,
        "matched_intervals": 24,
        "forecast_coverage": 1.0,
        "actual_coverage": 1.0,
        "matched_coverage": 1.0,
    }


def test_forecast_31_january_is_delivered_on_1_february(client):
    body = client.get("/api/forecast", params={"decision_date": "2026-01-31"}).json()
    assert body["delivery_date"] == "2026-02-01"
    assert body["coverage"]["matched_intervals"] == 24


def test_forecast_unavailable_intervals_are_null_with_no_error(client):
    # Before 02:30 the newest forecast does not reach the last delivery hours.
    response = client.get("/api/forecast", params={"decision_date": "2026-01-10", "decision_time": "00:00"})
    body = strict_json(response)
    missing = [i for i in body["intervals"] if i["forecast_mw"] is None]
    assert missing, "expected some intervals without an eligible forecast"
    for i in missing:
        assert i["forecast_publish_time"] is None and i["error_mw"] is None
        assert i["actual_mw"] is not None  # the actual is still reported
    c = body["coverage"]
    assert c["forecast_intervals"] == c["matched_intervals"] == 24 - len(missing)
    assert c["actual_intervals"] == 24


# ------------------------------------------------------------ /api/accuracy


def test_accuracy_returns_pooled_and_daily_results_with_definitions(client):
    response = client.get(
        "/api/accuracy", params={"start_date": "2026-01-01", "end_date": "2026-01-31", "decision_time": "10:00"}
    )
    assert response.status_code == 200
    body = strict_json(response)
    assert body["decision_count"] == 31 and len(body["days"]) == 31
    assert body["decision_time"] == "10:00"
    assert "demo assumption" in body["decision_time_note"].lower()
    assert "forecast - actual" in body["error_definition"]
    pooled = body["pooled"]
    assert pooled["expected_intervals"] == 744 and pooled["matched_intervals"] == 744
    for key in ("mae_mw", "rmse_mw", "bias_mw"):
        assert isinstance(pooled[key], float)
    assert sum(b["count"] for b in body["error_histogram"]) == pooled["matched_intervals"]


def test_accuracy_daily_rows_have_metrics_coverage_and_own_cutoff(client):
    days = client.get("/api/accuracy", params={"start_date": "2026-01-30", "end_date": "2026-01-31"}).json()["days"]
    assert [d["decision_date"] for d in days] == ["2026-01-30", "2026-01-31"]
    assert [d["delivery_date"] for d in days] == ["2026-01-31", "2026-02-01"]
    assert [d["decision_cutoff"] for d in days] == ["2026-01-30T10:00:00+00:00", "2026-01-31T10:00:00+00:00"]
    for d in days:
        for key in ("expected_intervals", "matched_intervals", "matched_coverage", "mae_mw", "rmse_mw", "bias_mw"):
            assert key in d


def test_accuracy_pooled_metrics_combine_daily_matched_intervals(client):
    body = client.get("/api/accuracy", params={"start_date": "2026-01-01", "end_date": "2026-01-03"}).json()
    days = body["days"]
    total = sum(d["matched_intervals"] for d in days)
    assert body["pooled"]["matched_intervals"] == total
    weighted_bias = sum(d["bias_mw"] * d["matched_intervals"] for d in days) / total
    assert body["pooled"]["bias_mw"] == pytest.approx(weighted_bias)  # pooled over intervals, not averaged per day


def test_accuracy_single_day_range(client):
    body = client.get("/api/accuracy", params={"start_date": "2026-01-15", "end_date": "2026-01-15"}).json()
    assert body["decision_count"] == 1 and body["pooled"]["expected_intervals"] == 24


def test_accuracy_defaults_to_all_of_january_at_10(client):
    body = client.get("/api/accuracy").json()
    assert (body["start_date"], body["end_date"], body["decision_time"]) == ("2026-01-01", "2026-01-31", "10:00")


def test_accuracy_changes_with_decision_time(client):
    early = client.get("/api/accuracy", params={"decision_time": "06:00"}).json()["pooled"]
    late = client.get("/api/accuracy", params={"decision_time": "16:00"}).json()["pooled"]
    assert early["mae_mw"] != late["mae_mw"]


def test_accuracy_metrics_are_null_not_zero_when_nothing_matches(client):
    original = client.app.state.dataset
    client.app.state.dataset = main.Dataset(original.actuals.iloc[0:0], original.forecasts, {})  # no actuals
    try:
        response = client.get("/api/accuracy", params={"start_date": "2026-01-15", "end_date": "2026-01-15"})
    finally:
        client.app.state.dataset = original
    pooled = strict_json(response)["pooled"]
    assert pooled["matched_intervals"] == 0 and pooled["forecast_intervals"] == 24
    assert pooled["mae_mw"] is None and pooled["rmse_mw"] is None and pooled["bias_mw"] is None


# ------------------------------------------------------------ input validation (client errors)


@pytest.mark.parametrize(
    "path, params, message",
    [
        ("/api/forecast", {"decision_date": "2026-02-01"}, "between 2026-01-01 and 2026-01-31"),
        ("/api/forecast", {"decision_date": "2025-12-31"}, "between 2026-01-01 and 2026-01-31"),
        ("/api/forecast", {"decision_date": "10-01-2026"}, "YYYY-MM-DD"),
        ("/api/forecast", {"decision_date": "2026-01-32"}, "YYYY-MM-DD"),
        ("/api/forecast", {"decision_date": ""}, "YYYY-MM-DD"),
        ("/api/forecast", {"decision_date": "2026-01-10", "decision_time": "25:00"}, "HH:MM"),
        ("/api/forecast", {"decision_date": "2026-01-10", "decision_time": "10am"}, "HH:MM"),
        ("/api/forecast", {"decision_date": "2026-01-10", "decision_time": "9:00"}, "HH:MM"),
        ("/api/accuracy", {"start_date": "2026-01-20", "end_date": "2026-01-10"}, "on or before"),
        ("/api/accuracy", {"start_date": "2026-01-01", "end_date": "2026-02-05"}, "end_date must be a decision date"),
        ("/api/accuracy", {"start_date": "yesterday"}, "start_date must be a date"),
        ("/api/accuracy", {"decision_time": "10:60"}, "HH:MM"),
    ],
)
def test_bad_input_is_rejected_with_a_helpful_422(client, path, params, message):
    response = client.get(path, params=params)
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_missing_decision_date_is_a_client_error(client):
    response = client.get("/api/forecast")
    assert response.status_code == 422
    assert "decision_date" in json.dumps(response.json())


def test_responses_contain_no_nan(client):
    for params in ({"decision_date": "2026-01-01", "decision_time": "00:00"}, {"decision_date": "2026-01-15"}):
        body = strict_json(client.get("/api/forecast", params=params))
        for i in body["intervals"]:
            for v in i.values():
                assert not (isinstance(v, float) and math.isnan(v))


# ------------------------------------------------------------ static frontend


@pytest.mark.skipif(not FRONTEND_DIST.is_dir(), reason="frontend not built (run npm run build)")
def test_root_serves_built_react_app(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root">' in response.text


def test_api_routes_take_priority_over_static_files(client):
    assert client.get("/api/health").headers["content-type"].startswith("application/json")


def test_removed_decision_endpoint_is_gone(client):
    assert client.get("/api/decision", params={"date": "2026-01-10"}).status_code in (404, 405)
