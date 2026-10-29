from datetime import date, time

import math

import pandas as pd
import pytest

from app import analysis
from app.analysis import (
    accuracy,
    cutoff_datetime,
    decision_table,
    delivery_hours,
    error_metrics,
    hourly_actuals,
    parse_cutoff,
    select_forecasts,
)

DECISION = date(2026, 1, 1)  # delivery day is 2 Jan 2026
TEN = time(10, 0)
FIRST_HOUR = "2026-01-02T00:00:00Z"


def forecasts_frame(rows):
    """rows: (publish_time, start_time, generation_mw) as UTC strings."""
    df = pd.DataFrame(rows, columns=["publish_time", "start_time", "generation_mw"])
    df["publish_time"] = pd.to_datetime(df["publish_time"], utc=True)
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["generation_mw"] = df["generation_mw"].astype(float)
    return df


def actuals_frame(rows):
    """rows: (start_time, generation_mw)."""
    df = pd.DataFrame(rows, columns=["start_time", "generation_mw"])
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["generation_mw"] = df["generation_mw"].astype(float)
    return df


def first_hour(table, col):
    return table.loc[pd.Timestamp(FIRST_HOUR), col]


# ------------------------------------------------------------ time handling


def test_cutoff_is_london_time_converted_to_utc():
    # January: London = UTC. June: London = UTC+1, so 10:00 London = 09:00 UTC.
    assert cutoff_datetime(date(2026, 1, 1), TEN) == pd.Timestamp("2026-01-01T10:00Z")
    assert cutoff_datetime(date(2026, 6, 1), TEN) == pd.Timestamp("2026-06-01T09:00Z")


@pytest.mark.parametrize(
    "decision_date, expected_hours",
    [
        (date(2026, 1, 1), 24),
        (date(2026, 3, 28), 23),  # delivery 29 Mar 2026: clocks go forward
        (date(2026, 10, 24), 25),  # delivery 25 Oct 2026: clocks go back
    ],
)
def test_delivery_day_hours_follow_london_calendar(decision_date, expected_hours):
    hours = delivery_hours(decision_date)
    assert len(hours) == expected_hours
    assert str(hours.tz) == "UTC"


def test_delivery_day_of_31_january_is_1_february():
    hours = delivery_hours(date(2026, 1, 31))
    assert hours[0] == pd.Timestamp("2026-02-01T00:00Z")
    assert hours[-1] == pd.Timestamp("2026-02-01T23:00Z")


@pytest.mark.parametrize("text", ["10:00", "00:00", "23:59"])
def test_parse_cutoff_accepts_valid_times(text):
    assert parse_cutoff(text).strftime("%H:%M") == text


@pytest.mark.parametrize("text", ["24:00", "9:00", "10:60", "10", "", "abc"])
def test_parse_cutoff_rejects_invalid_times(text):
    with pytest.raises(ValueError):
        parse_cutoff(text)


# ------------------------------------------------------------ forecast selection


def test_picks_latest_forecast_published_before_cutoff():
    f = forecasts_frame(
        [
            ("2026-01-01T04:30Z", FIRST_HOUR, 100),
            ("2026-01-01T09:30Z", FIRST_HOUR, 200),
            ("2026-01-01T07:30Z", FIRST_HOUR, 150),
        ]
    )
    table = select_forecasts(f, DECISION, TEN)
    assert first_hour(table, "forecast_mw") == 200
    assert first_hour(table, "publish_time") == pd.Timestamp("2026-01-01T09:30Z")


def test_forecast_published_exactly_at_cutoff_is_eligible():
    f = forecasts_frame([("2026-01-01T10:00Z", FIRST_HOUR, 300)])
    assert first_hour(select_forecasts(f, DECISION, TEN), "forecast_mw") == 300


def test_forecast_published_after_cutoff_is_never_used():
    f = forecasts_frame(
        [
            ("2026-01-01T09:30Z", FIRST_HOUR, 200),
            ("2026-01-01T10:01Z", FIRST_HOUR, 999),  # one minute too late
            ("2026-01-01T11:30Z", FIRST_HOUR, 999),
        ]
    )
    assert first_hour(select_forecasts(f, DECISION, TEN), "forecast_mw") == 200


def test_selection_is_per_hour_and_falls_back_to_older_publication():
    second_hour = "2026-01-02T01:00:00Z"
    f = forecasts_frame(
        [
            ("2026-01-01T07:30Z", FIRST_HOUR, 100),
            ("2026-01-01T07:30Z", second_hour, 110),
            ("2026-01-01T09:30Z", FIRST_HOUR, 200),  # newest publication lacks hour 2
        ]
    )
    table = select_forecasts(f, DECISION, TEN)
    assert first_hour(table, "forecast_mw") == 200
    assert table.loc[pd.Timestamp(second_hour), "forecast_mw"] == 110


def test_hour_without_eligible_forecast_is_kept_as_missing():
    f = forecasts_frame([("2026-01-01T11:30Z", FIRST_HOUR, 999)])  # only after cutoff
    table = select_forecasts(f, DECISION, TEN)
    assert len(table) == 24  # no hour is dropped
    assert table["forecast_mw"].isna().all()
    assert table["publish_time"].isna().all()


def test_forecast_row_without_value_does_not_hide_older_forecast():
    f = forecasts_frame(
        [("2026-01-01T07:30Z", FIRST_HOUR, 100), ("2026-01-01T09:30Z", FIRST_HOUR, None)]
    )
    assert first_hour(select_forecasts(f, DECISION, TEN), "forecast_mw") == 100


def test_later_cutoff_can_use_later_publication():
    f = forecasts_frame(
        [("2026-01-01T09:30Z", FIRST_HOUR, 200), ("2026-01-01T11:30Z", FIRST_HOUR, 250)]
    )
    assert first_hour(select_forecasts(f, DECISION, time(12, 0)), "forecast_mw") == 250


# ------------------------------------------------------------ actual alignment


def test_hourly_actual_is_mean_of_both_half_hours():
    a = actuals_frame([("2026-01-02T00:00Z", 100), ("2026-01-02T00:30Z", 200)])
    hours = pd.DatetimeIndex([pd.Timestamp(FIRST_HOUR)])
    assert hourly_actuals(a, hours).iloc[0] == 150


@pytest.mark.parametrize(
    "rows",
    [
        [("2026-01-02T00:00Z", 100)],  # second half-hour absent
        [("2026-01-02T00:30Z", 200)],  # first half-hour absent
        [("2026-01-02T00:00Z", 100), ("2026-01-02T00:30Z", None)],  # value is NaN
    ],
)
def test_hourly_actual_is_missing_if_either_half_hour_is_missing(rows):
    hours = pd.DatetimeIndex([pd.Timestamp(FIRST_HOUR)])
    assert math.isnan(hourly_actuals(actuals_frame(rows), hours).iloc[0])


def test_31_january_decision_is_scored_with_1_february_actuals():
    f = forecasts_frame([("2026-01-31T09:30Z", "2026-02-01T00:00Z", 110)])
    a = actuals_frame([("2026-02-01T00:00Z", 100), ("2026-02-01T00:30Z", 100)])
    table = decision_table(a, f, date(2026, 1, 31), TEN)
    assert table.loc[pd.Timestamp("2026-02-01T00:00Z"), "error_mw"] == 10


# ------------------------------------------------------------ errors and metrics


def test_error_is_forecast_minus_actual_and_lead_time_is_reported():
    f = forecasts_frame([("2026-01-01T09:30Z", FIRST_HOUR, 110)])
    a = actuals_frame([("2026-01-02T00:00Z", 100), ("2026-01-02T00:30Z", 100)])
    table = decision_table(a, f, DECISION, TEN)
    assert first_hour(table, "error_mw") == 10  # positive = over-forecast
    assert first_hour(table, "lead_time_hours") == 14.5


def test_error_metrics_known_values():
    m = error_metrics(pd.Series([10.0, -10.0, 20.0, float("nan")]))
    assert m["n"] == 3  # NaN ignored
    assert m["mae_mw"] == pytest.approx(40 / 3)
    assert m["rmse_mw"] == pytest.approx(math.sqrt(600 / 3))
    assert m["bias_mw"] == pytest.approx(20 / 3)
    assert m["p50_mw"] == pytest.approx(10)


def test_error_metrics_with_no_data_are_none_not_zero():
    m = error_metrics(pd.Series([float("nan")]))
    assert m["n"] == 0
    assert m["mae_mw"] is None and m["bias_mw"] is None


def test_coverage_counts_missing_hours():
    f = forecasts_frame([("2026-01-01T09:30Z", FIRST_HOUR, 110)])
    a = actuals_frame([("2026-01-02T00:00Z", 100), ("2026-01-02T00:30Z", 100)])
    result = accuracy(a, f, [DECISION], TEN)
    day = result["days"].iloc[0]
    assert day["expected_hours"] == 24
    assert day["paired_hours"] == 1
    assert day["paired_coverage"] == pytest.approx(1 / 24)
    assert result["overall"]["n"] == 1


# ------------------------------------------------------------ real snapshot


@pytest.fixture(scope="module")
def snapshot():
    return analysis.load_snapshot()


JANUARY = [date(2026, 1, d) for d in range(1, 32)]


def test_snapshot_january_at_default_cutoff_has_full_coverage(snapshot):
    actuals, forecasts = snapshot
    overall = accuracy(actuals, forecasts, JANUARY, analysis.DEFAULT_CUTOFF)["overall"]
    assert overall["expected_hours"] == 31 * 24
    assert overall["paired_coverage"] == 1.0


@pytest.mark.parametrize("cutoff", [time(0, 0), time(10, 0), time(23, 59)])
def test_snapshot_never_uses_forecast_published_after_cutoff(snapshot, cutoff):
    actuals, forecasts = snapshot
    hours = accuracy(actuals, forecasts, JANUARY, cutoff)["hours"]
    cutoffs = hours["decision_date"].map(lambda d: cutoff_datetime(d, cutoff))
    used = hours["publish_time"].notna()
    assert (hours.loc[used, "publish_time"] <= cutoffs[used]).all()
