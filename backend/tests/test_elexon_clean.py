from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.elexon import clean_actuals, clean_forecasts

LONDON = ZoneInfo("Europe/London")
START = datetime(2026, 1, 2, tzinfo=LONDON)
END = datetime(2026, 1, 3, tzinfo=LONDON)


def actual(start, generation, publish="2026-01-03T00:00:00Z", fuel="WIND"):
    return {"startTime": start, "publishTime": publish, "fuelType": fuel, "generation": generation}


def forecast(publish, start, generation):
    return {"publishTime": publish, "startTime": start, "generation": generation}


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


def test_actuals_duplicate_start_time_keeps_latest_publish():
    rows = [
        actual("2026-01-02T00:00:00Z", 200, publish="2026-01-02T05:00:00Z"),
        actual("2026-01-02T00:00:00Z", 100, publish="2026-01-02T01:00:00Z"),
    ]
    df, report = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [200]
    assert report["duplicate_start_times_removed"] == 1


def test_actuals_window_is_start_inclusive_end_exclusive():
    rows = [
        actual("2026-01-01T23:30:00Z", 1),  # before window
        actual("2026-01-02T00:00:00Z", 2),  # first interval
        actual("2026-01-02T23:30:00Z", 3),  # last interval
        actual("2026-01-03T00:00:00Z", 4),  # next day, excluded
    ]
    df, _ = clean_actuals(rows, START, END)
    assert df["generation_mw"].tolist() == [2, 3]


def test_forecasts_keep_every_publication_and_remove_exact_duplicates():
    rows = [
        forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 10),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 20),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T00:00:00Z", 20),  # chunk-boundary duplicate
    ]
    df, report = clean_forecasts(rows, START, END)
    assert df["generation_mw"].tolist() == [10, 20]
    assert report["publications"] == 2
    assert report["duplicate_rows_removed"] == 1


def test_forecasts_outside_delivery_window_are_dropped():
    rows = [
        forecast("2026-01-01T09:30:00Z", "2026-01-01T23:00:00Z", 1),
        forecast("2026-01-01T09:30:00Z", "2026-01-02T23:00:00Z", 2),
        forecast("2026-01-01T09:30:00Z", "2026-01-03T00:00:00Z", 3),
    ]
    df, _ = clean_forecasts(rows, START, END)
    assert df["generation_mw"].tolist() == [2]
