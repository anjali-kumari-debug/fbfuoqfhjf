from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.elexon import clean_actuals, clean_forecasts

LONDON = ZoneInfo("Europe/London")
START = datetime(2026, 1, 2, tzinfo=LONDON)
END = datetime(2026, 1, 3, tzinfo=LONDON)


def actual(start, generation, publish="2026-01-03T00:00:00Z", fuel="WIND", sdate="2026-01-02", period=1):
    return {
        "startTime": start,
        "publishTime": publish,
        "settlementDate": sdate,
        "settlementPeriod": period,
        "fuelType": fuel,
        "generation": generation,
    }


def forecast(publish, start, generation):
    return {"publishTime": publish, "startTime": start, "generation": generation}


# ------------------------------------------------------------ actuals


def test_actuals_timestamps_are_timezone_aware_utc():
    df, _ = clean_actuals([actual("2026-01-02T00:00:00Z", 100)], START, END)
    assert str(df["start_time"].dt.tz) == "UTC"


def test_actuals_keep_missing_generation_as_nan_not_zero():
    df, report = clean_actuals([actual("2026-01-02T00:00:00Z", None)], START, END)
    assert len(df) == 1
    assert pd.isna(df.loc[0, "generation_mw"])
    assert report["missing_generation_values"] == 1


def test_actuals_drop_non_wind_rows():
    rows = [actual("2026-01-02T00:00:00Z", 100), actual("2026-01-02T00:00:00Z", 999, fuel="CCGT")]
    df, report = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [100]
    assert report["non_wind_rows_removed"] == 1


def test_actuals_exact_duplicates_are_removed_and_counted():
    row = actual("2026-01-02T00:00:00Z", 100)
    df, report = clean_actuals([row, dict(row)], START, END)
    assert df["generation_mw"].tolist() == [100]
    assert report["exact_duplicates_removed"] == 1
    assert report["conflicting_start_times"] == 0


def test_actuals_conflict_with_later_publish_time_keeps_latest_revision_and_reports_it():
    rows = [
        actual("2026-01-02T00:00:00Z", 200, publish="2026-01-02T05:00:00Z"),
        actual("2026-01-02T00:00:00Z", 100, publish="2026-01-02T01:00:00Z"),
    ]
    df, report = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [200]
    assert report["conflicting_start_times"] == 1
    assert report["conflicts_resolved_as_latest_revision"] == 1
    assert report["conflict_examples"][0]["start_time"] == "2026-01-02T00:00:00Z"


def test_actuals_conflict_without_a_principled_winner_becomes_missing():
    rows = [
        actual("2026-01-02T00:00:00Z", 200, publish="2026-01-02T01:00:00Z"),
        actual("2026-01-02T00:00:00Z", 100, publish="2026-01-02T01:00:00Z"),  # same publish time
    ]
    df, report = clean_actuals(rows, START, END)
    assert len(df) == 1  # the interval is kept...
    assert pd.isna(df.loc[0, "generation_mw"])  # ...but no value is invented or picked
    assert report["conflicts_set_to_missing"] == 1


def test_actuals_missing_publish_time_never_wins_a_conflict():
    rows = [
        actual("2026-01-02T00:00:00Z", 200, publish="2026-01-02T05:00:00Z"),
        actual("2026-01-02T00:00:00Z", 999, publish=None),
    ]
    df, report = clean_actuals(rows, START, END)
    assert pd.isna(df.loc[0, "generation_mw"])
    assert report["conflicts_set_to_missing"] == 1


def test_actuals_window_is_start_inclusive_end_exclusive():
    rows = [
        actual("2026-01-01T23:30:00Z", 1),  # before window
        actual("2026-01-02T00:00:00Z", 2),  # first interval
        actual("2026-01-02T23:30:00Z", 3, period=48),  # last interval
        actual("2026-01-03T00:00:00Z", 4),  # next day, excluded
    ]
    df, _ = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [2, 3]


def test_actuals_invalid_timestamps_and_off_grid_rows_are_removed_and_counted():
    rows = [
        actual("2026-01-02T00:00:00Z", 1),
        actual(None, 2),
        actual("not a date", 3),
        actual("2026-01-02T00:15:00Z", 4),  # not on the half-hour grid
    ]
    df, report = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [1]
    assert report["rows_without_valid_start_time_removed"] == 2
    assert report["rows_off_half_hour_grid_removed"] == 1


def test_actuals_non_numeric_and_infinite_values_become_missing_and_negatives_are_flagged():
    rows = [
        actual("2026-01-02T00:00:00Z", "abc"),
        actual("2026-01-02T00:30:00Z", float("inf"), period=2),
        actual("2026-01-02T01:00:00Z", -5, period=3),
    ]
    df, report = clean_actuals(rows, START, END)
    assert pd.isna(df.loc[0, "generation_mw"]) and pd.isna(df.loc[1, "generation_mw"])
    assert df.loc[2, "generation_mw"] == -5  # kept as reported by the source
    assert report["generation_not_numeric"] == 1
    assert report["generation_not_finite"] == 1
    assert report["generation_negative"] == 1


def test_actuals_settlement_fields_are_checked_against_start_time():
    rows = [actual("2026-01-02T00:00:00Z", 1, period=1), actual("2026-01-02T00:30:00Z", 2, period=5)]
    _, report = clean_actuals(rows, START, END)
    assert report["settlement_fields_inconsistent"] == 1


# ------------------------------------------------------------ forecasts


def test_forecasts_keep_every_publication_and_remove_exact_duplicates():
    rows = [
        forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 10),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 20),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 20),  # exact copy
    ]
    df, report = clean_forecasts(rows, START, END)
    assert df["generation_mw"].tolist() == [10, 20]
    assert report["publications"] == 2
    assert report["exact_duplicates_removed"] == 1


def test_forecasts_published_before_the_decision_month_are_kept():
    rows = [forecast("2025-12-31T02:30:00Z", "2026-01-02T00:00:00Z", 10)]
    df, report = clean_forecasts(rows, START, END)
    assert len(df) == 1
    assert report["earliest_publication"] == "2025-12-31T02:30:00Z"


def test_forecasts_conflicting_values_are_reported_and_set_to_missing():
    rows = [
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 20),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 25),
    ]
    df, report = clean_forecasts(rows, START, END)
    assert len(df) == 1 and pd.isna(df.loc[0, "generation_mw"])
    assert report["conflicting_keys_set_to_missing"] == 1
    assert report["conflict_examples"][0]["publish_time"] == "2026-01-01T09:30:00Z"


def test_forecast_rows_without_timestamps_or_off_the_hour_are_counted_and_removed():
    rows = [
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 10),
        forecast(None, "2026-01-02T00:00:00Z", 999),  # unknown publish time: cannot prove no look-ahead
        forecast("2026-01-01T09:30:00Z", None, 999),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:30:00Z", 999),  # not on the hour
    ]
    df, report = clean_forecasts(rows, START, END)
    assert df["generation_mw"].tolist() == [10]
    assert report["rows_without_valid_timestamps_removed"] == 2
    assert report["rows_off_hour_grid_removed"] == 1


def test_forecasts_outside_delivery_window_are_dropped():
    rows = [
        forecast("2026-01-01T09:30:00Z", "2026-01-01T23:00:00Z", 1),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T23:00:00Z", 2),
        forecast("2026-01-01T09:30:00Z", "2026-01-03T00:00:00Z", 3),
    ]
    df, _ = clean_forecasts(rows, START, END)
    assert df["generation_mw"].tolist() == [2]


def test_actuals_empty_later_copy_does_not_overwrite_a_real_value():
    # Reviewer's case: 15000 published 00:30, then an empty row published 01:00.
    rows = [
        actual("2026-01-02T00:00:00Z", 15000, publish="2026-01-02T00:30:00Z"),
        actual("2026-01-02T00:00:00Z", None, publish="2026-01-02T01:00:00Z"),
    ]
    df, report = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [15000]
    assert report["conflicting_start_times"] == 0  # an empty copy is not a competing value


def test_forecasts_empty_duplicate_does_not_hide_a_real_value():
    rows = [
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 5000),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", None),
    ]
    df, report = clean_forecasts(rows, START, END)
    assert df["generation_mw"].tolist() == [5000]
    assert report["conflicting_keys_set_to_missing"] == 0
