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
    assert day["expected_intervals"] == 24
    assert day["matched_intervals"] == 1
    assert day["matched_coverage"] == pytest.approx(1 / 24)
    assert result["overall"]["n"] == 1


# ------------------------------------------------------------ real snapshot


@pytest.fixture(scope="module")
def snapshot():
    return analysis.load_data()


JANUARY = [date(2026, 1, d) for d in range(1, 32)]


def test_snapshot_january_at_default_cutoff_has_full_coverage(snapshot):
    actuals, forecasts = snapshot
    overall = accuracy(actuals, forecasts, JANUARY, analysis.DEFAULT_CUTOFF)["overall"]
    assert overall["expected_intervals"] == 31 * 24
    assert overall["matched_coverage"] == 1.0


@pytest.mark.parametrize("cutoff", [time(0, 0), time(10, 0), time(23, 59)])
def test_snapshot_never_uses_forecast_published_after_cutoff(snapshot, cutoff):
    actuals, forecasts = snapshot
    hours = accuracy(actuals, forecasts, JANUARY, cutoff)["hours"]
    cutoffs = hours["decision_date"].map(lambda d: cutoff_datetime(d, cutoff))
    used = hours["publish_time"].notna()
    assert (hours.loc[used, "publish_time"] <= cutoffs[used]).all()


# ------------------------------------------------------------ edge cases added for the analysis spec

H = ["2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z", "2026-01-02T02:00:00Z", "2026-01-02T03:00:00Z", "2026-01-02T04:00:00Z"]


def half_hours(hour, value):
    """Both half-hours of an hour with the same value, so the hourly mean equals value."""
    start = pd.Timestamp(hour)
    return [(start.isoformat(), value), ((start + pd.Timedelta(minutes=30)).isoformat(), value)]


def test_hand_calculated_metrics_use_only_matched_pairs():
    # hour:      0     1     2     3 (no actual)   4 (no forecast)
    # forecast: 110    90   130    500             -
    # actual:   100   100   100     -             100
    # errors:   +10   -10   +30
    # MAE  = (10 + 10 + 30) / 3            = 16.667
    # RMSE = sqrt((100 + 100 + 900) / 3)   = 19.149
    # bias = (10 - 10 + 30) / 3            = 10.0
    f = forecasts_frame([("2026-01-01T09:30Z", h, v) for h, v in zip(H[:4], [110, 90, 130, 500])])
    a = actuals_frame(half_hours(H[0], 100) + half_hours(H[1], 100) + half_hours(H[2], 100) + half_hours(H[4], 100))
    table = decision_table(a, f, DECISION, TEN)
    m = error_metrics(table["error_mw"])
    assert m["n"] == 3
    assert m["mae_mw"] == pytest.approx(50 / 3)
    assert m["rmse_mw"] == pytest.approx(math.sqrt(1100 / 3))
    assert m["bias_mw"] == pytest.approx(10.0)
    c = analysis.coverage(table)
    assert (c["expected_intervals"], c["forecast_intervals"], c["actual_intervals"], c["matched_intervals"]) == (24, 4, 4, 3)


def test_legitimate_zero_generation_is_a_real_value_not_missing():
    f = forecasts_frame([("2026-01-01T09:30Z", FIRST_HOUR, 0)])
    a = actuals_frame(half_hours(FIRST_HOUR, 0))
    table = decision_table(a, f, DECISION, TEN)
    assert first_hour(table, "forecast_mw") == 0
    assert first_hour(table, "actual_mw") == 0
    assert first_hour(table, "error_mw") == 0
    m = error_metrics(table["error_mw"])
    assert m["n"] == 1 and m["mae_mw"] == 0  # zero error, not None


def test_no_matched_intervals_gives_null_metrics_and_separate_counts():
    f = forecasts_frame([("2026-01-01T09:30Z", FIRST_HOUR, 110)])
    a = actuals_frame(half_hours(H[1], 100))  # actual only for a different hour
    result = accuracy(a, f, [DECISION], TEN)
    day = result["days"].iloc[0]
    assert (day["expected_intervals"], day["forecast_intervals"], day["actual_intervals"], day["matched_intervals"]) == (24, 1, 1, 0)
    assert result["overall"]["n"] == 0
    for key in ("mae_mw", "rmse_mw", "bias_mw", "p50_mw"):
        assert result["overall"][key] is None


def test_month_analysis_uses_each_decision_dates_own_cutoff():
    # Published 1 Jan 11:00, after the 1 Jan 10:00 cutoff but long before a month-end cutoff.
    f = forecasts_frame(
        [
            ("2026-01-01T09:30Z", FIRST_HOUR, 100),
            ("2026-01-01T11:00Z", FIRST_HOUR, 999),
            ("2026-01-02T09:30Z", "2026-01-03T00:00:00Z", 200),
        ]
    )
    hours = accuracy(actuals_frame([]), f, [date(2026, 1, 1), date(2026, 1, 2)], TEN)["hours"]
    first_decision = hours[hours["decision_date"] == date(2026, 1, 1)]
    assert first_decision.loc[pd.Timestamp(FIRST_HOUR), "forecast_mw"] == 100  # not the 11:00 forecast
    second_decision = hours[hours["decision_date"] == date(2026, 1, 2)]
    assert second_decision.loc[pd.Timestamp("2026-01-03T00:00Z"), "forecast_mw"] == 200


def test_exact_duplicate_actuals_are_harmless():
    a = actuals_frame(half_hours(FIRST_HOUR, 100) * 2)  # every row twice
    hours = pd.DatetimeIndex([pd.Timestamp(FIRST_HOUR)])
    assert hourly_actuals(a, hours).iloc[0] == 100


def test_conflicting_duplicate_actuals_become_missing():
    a = actuals_frame(half_hours(FIRST_HOUR, 100) + [(FIRST_HOUR, 999)])
    hours = pd.DatetimeIndex([pd.Timestamp(FIRST_HOUR)])
    assert math.isnan(hourly_actuals(a, hours).iloc[0])


@pytest.mark.parametrize("order", [(10, 20), (20, 10)])
def test_conflicting_duplicate_forecasts_are_never_picked_by_row_order(order):
    f = forecasts_frame(
        [
            ("2026-01-01T07:30Z", FIRST_HOUR, 50),
            ("2026-01-01T09:30Z", FIRST_HOUR, order[0]),
            ("2026-01-01T09:30Z", FIRST_HOUR, order[1]),  # same publication and hour, different value
        ]
    )
    table = select_forecasts(f, DECISION, TEN)
    assert first_hour(table, "forecast_mw") == 50  # conflict is unusable: fall back to older publication
    assert first_hour(table, "publish_time") == pd.Timestamp("2026-01-01T07:30Z")


def test_exact_duplicate_forecasts_are_harmless():
    row = ("2026-01-01T09:30Z", FIRST_HOUR, 120)
    assert first_hour(select_forecasts(forecasts_frame([row, row]), DECISION, TEN), "forecast_mw") == 120


def test_load_data_parses_timestamps_as_utc_and_selection_ignores_row_order(tmp_path):
    (tmp_path / "actuals.csv").write_text(
        "start_time,generation_mw\n"
        "2026-01-02T00:30:00Z,300\n"  # out of order
        "2026-01-02T00:00:00+00:00,100\n"  # explicit offset instead of Z
    )
    (tmp_path / "forecasts.csv").write_text(
        "publish_time,start_time,generation_mw\n"
        "2026-01-01T09:30:00Z,2026-01-02T00:00:00Z,250\n"
        "2026-01-01T04:30:00Z,2026-01-02T00:00:00Z,150\n"  # older publication listed last
        "2026-01-01T07:30:00Z,2026-01-02T00:00:00Z,,\n".rstrip(",\n") + "\n"
    )
    actuals, forecasts = analysis.load_data(tmp_path)
    for col in (actuals["start_time"], forecasts["publish_time"], forecasts["start_time"]):
        assert str(col.dt.tz) == "UTC"
    assert pd.isna(forecasts["generation_mw"]).sum() == 1  # empty stays missing, not 0
    table = decision_table(actuals, forecasts, DECISION, TEN)
    assert first_hour(table, "forecast_mw") == 250  # latest by time, not by row position
    assert first_hour(table, "actual_mw") == 200


def test_empty_duplicate_forecast_does_not_hide_newest_real_value():
    # Reviewer's case: newest publication has 5000 and an empty copy for the same hour.
    f = forecasts_frame(
        [
            ("2026-01-01T07:30Z", FIRST_HOUR, 1000),
            ("2026-01-01T09:30Z", FIRST_HOUR, 5000),
            ("2026-01-01T09:30Z", FIRST_HOUR, None),
        ]
    )
    table = select_forecasts(f, DECISION, TEN)
    assert first_hour(table, "forecast_mw") == 5000
    assert first_hour(table, "publish_time") == pd.Timestamp("2026-01-01T09:30Z")


def test_empty_duplicate_actual_does_not_hide_real_value():
    a = actuals_frame(half_hours(FIRST_HOUR, 100) + [(FIRST_HOUR, None)])
    assert hourly_actuals(a, pd.DatetimeIndex([pd.Timestamp(FIRST_HOUR)])).iloc[0] == 100


@pytest.mark.parametrize(
    "decision_date, cutoff, expected_utc",
    [
        (date(2026, 3, 29), time(1, 30), "2026-03-29T01:30Z"),  # 01:30 does not exist (clocks jump 01:00->02:00)
        (date(2026, 10, 25), time(1, 30), "2026-10-25T00:30Z"),  # 01:30 happens twice: the first (BST) is used
    ],
)
def test_cutoff_on_clock_change_days_is_well_defined(decision_date, cutoff, expected_utc):
    assert cutoff_datetime(decision_date, cutoff) == pd.Timestamp(expected_utc)


# ------------------------------------------------------------ recent error profile (decision support)


def published_actuals(rows):
    """rows: (start_time, generation_mw, publish_time) as UTC strings."""
    df = pd.DataFrame(rows, columns=["start_time", "generation_mw", "publish_time"])
    for col in ("start_time", "publish_time"):
        df[col] = pd.to_datetime(df[col], utc=True)
    df["generation_mw"] = df["generation_mw"].astype(float)
    return df


def test_p90_abs_error_is_part_of_error_metrics():
    m = error_metrics(pd.Series([-1000.0] + [100.0] * 9))
    assert m["p90_abs_error_mw"] == pytest.approx(190.0)  # numpy linear interpolation between 100 and 1000


def test_recent_profile_uses_only_past_decisions_and_published_actuals():
    decision = date(2026, 1, 10)  # cutoff 10:00Z; history = decisions 3-9 Jan
    f = forecasts_frame(
        [
            ("2026-01-08T09:30:00Z", "2026-01-09T00:00:00Z", 1100),  # decision 8 Jan -> delivery 9 Jan
            ("2026-01-09T09:30:00Z", "2026-01-10T00:00:00Z", 1300),  # decision 9 Jan -> delivery 10 Jan
            ("2026-01-10T09:30:00Z", "2026-01-11T00:00:00Z", 9999),  # today's own decision: never used
        ]
    )
    a = published_actuals(
        [
            ("2026-01-09T00:00:00Z", 1000, "2026-01-09T00:30:00Z"),
            ("2026-01-09T00:30:00Z", 1000, "2026-01-09T01:00:00Z"),
            ("2026-01-10T00:00:00Z", 1000, "2026-01-10T00:30:00Z"),  # published before today's cutoff
            ("2026-01-10T00:30:00Z", 1000, "2026-01-10T11:00:00Z"),  # published AFTER the cutoff
            ("2026-01-11T00:00:00Z", 0, "2026-01-11T00:30:00Z"),  # the future
            ("2026-01-11T00:30:00Z", 0, "2026-01-11T01:00:00Z"),
        ]
    )
    p = analysis.recent_error_profile(a, f, decision, TEN)
    # Only the 9 Jan hour is matched: error +100. The 10 Jan hour lacks a published second half,
    # and 11 Jan (today's delivery) is never part of the history.
    assert p["matched_intervals"] == 1
    assert p["bias_mw"] == pytest.approx(100)
    assert (p["window_first_decision"], p["window_last_decision"]) == ("2026-01-03", "2026-01-09")


def test_recent_profile_history_uses_each_past_decisions_own_cutoff():
    f = forecasts_frame(
        [
            ("2026-01-08T09:30:00Z", "2026-01-09T00:00:00Z", 1100),
            ("2026-01-08T11:00:00Z", "2026-01-09T00:00:00Z", 5000),  # after 8 Jan's 10:00 cutoff
        ]
    )
    a = published_actuals([("2026-01-09T00:00:00Z", 1000, "2026-01-09T00:30:00Z"),
                           ("2026-01-09T00:30:00Z", 1000, "2026-01-09T01:00:00Z")])
    assert analysis.recent_error_profile(a, f, date(2026, 1, 10), TEN)["bias_mw"] == pytest.approx(100)


def test_recent_profile_is_empty_not_zero_without_history():
    f = forecasts_frame([("2026-01-01T09:30:00Z", FIRST_HOUR, 100)])
    a = published_actuals([("2026-01-02T00:00:00Z", 100, "2026-01-02T00:30:00Z")])
    p = analysis.recent_error_profile(a, f, date(2026, 1, 1), TEN)
    assert p["matched_intervals"] == 0 and p["decisions_with_data"] == 0
    assert p["bias_mw"] is None and p["p10_mw"] is None and p["p90_abs_error_mw"] is None


def test_recent_profile_on_real_data_is_available_from_early_january():
    actuals, forecasts = analysis.load_data()
    first = analysis.recent_error_profile(actuals, forecasts, date(2026, 1, 1), TEN)
    assert first["matched_intervals"] == 0  # nothing delivered yet
    mid = analysis.recent_error_profile(actuals, forecasts, date(2026, 1, 15), TEN)
    assert mid["decisions_with_data"] == 7 and mid["matched_intervals"] > 7 * 20
