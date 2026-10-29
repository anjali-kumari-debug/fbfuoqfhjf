import math
from datetime import date, time

import pandas as pd
import pytest

from app import evaluate


def s(values):
    return pd.Series(values, dtype=float)


def test_extended_metrics_hand_calculated():
    # errors: +500, -1500, +2500 ; actuals 10000 each
    m = evaluate.extended_metrics(s([10500, 8500, 12500]), s([10000, 10000, 10000]))
    assert m["n"] == 3
    assert m["mae_mw"] == pytest.approx(1500)
    assert m["rmse_mw"] == pytest.approx(math.sqrt((500**2 + 1500**2 + 2500**2) / 3))
    assert m["bias_mw"] == pytest.approx(500)
    assert m["median_error_mw"] == pytest.approx(500)
    assert m["nmae_pct"] == pytest.approx(15.0)
    assert m["wape_pct"] == pytest.approx(15.0)
    assert m["within_1gw_pct"] == pytest.approx(100 / 3)
    assert m["within_2gw_pct"] == pytest.approx(200 / 3)
    assert m["over_forecast_pct"] == pytest.approx(200 / 3)


def test_extended_metrics_use_matched_pairs_only_and_null_when_none():
    m = evaluate.extended_metrics(s([100, None, 300]), s([100, 200, None]))
    assert m["n"] == 1 and m["mae_mw"] == 0
    empty = evaluate.extended_metrics(s([None]), s([5]))
    assert empty["n"] == 0 and empty["mae_mw"] is None and empty["wape_pct"] is None


def test_zero_actuals_do_not_break_scale_free_metrics():
    m = evaluate.extended_metrics(s([0, 0]), s([0, 0]))
    assert m["mae_mw"] == 0 and m["nmae_pct"] is None and m["wape_pct"] is None


def test_skill_score():
    assert evaluate.skill_score(50, 100) == pytest.approx(0.5)
    assert evaluate.skill_score(100, 100) == 0
    assert evaluate.skill_score(150, 100) == pytest.approx(-0.5)
    assert evaluate.skill_score(None, 100) is None and evaluate.skill_score(10, 0) is None


def test_persistence_uses_only_actuals_published_by_the_cutoff():
    actuals = pd.DataFrame(
        {
            "start_time": pd.to_datetime(["2026-01-01T09:00:00Z", "2026-01-01T09:30:00Z"], utc=True),
            "publish_time": pd.to_datetime(["2026-01-01T09:30:00Z", "2026-01-01T10:00:01Z"], utc=True),
            "generation_mw": [111.0, 999.0],
        }
    )
    # The 09:30 half-hour was published one second after the 10:00 cutoff: it must not be used.
    assert evaluate.persistence_value(actuals, date(2026, 1, 1), time(10, 0)) == 111
    assert math.isnan(evaluate.persistence_value(actuals, date(2026, 1, 1), time(9, 0)))


def test_buckets():
    assert list(evaluate.lead_time_bucket(pd.Series([14.5, 18, 37.5])).astype(str)) == ["<18 h", "18-24 h", ">=36 h"]
    assert list(evaluate.actual_level_bucket(pd.Series([0, 4999, 15000])).astype(str)) == ["<5 GW", "<5 GW", ">=15 GW"]


def test_report_runs_on_real_data():
    text = evaluate.report(time(10, 0), [date(2026, 1, d) for d in range(1, 32)])
    assert "Persistence baseline" in text and "By lead time" in text


def test_rolling_bias_correction_has_no_look_ahead():
    # Delivery day k has error k*100 for decision day k-1. Huge error on the decision's own delivery day.
    idx = pd.to_datetime([f"2026-01-{d:02d}T12:00:00Z" for d in range(2, 8)], utc=True)
    hours = pd.DataFrame(
        {
            "decision_date": [date(2026, 1, d - 1) for d in range(2, 8)],
            "delivery_date": [date(2026, 1, d) for d in range(2, 8)],
            "forecast_mw": 1000.0,
            "error_mw": [100.0, 200.0, 300.0, 400.0, 99999.0, 500.0],
        },
        index=idx,
    )
    corrected = evaluate.rolling_bias_correction(hours, window_days=7)
    # Decisions 1-3 Jan: no delivery day <= D-2 exists yet in this data.
    assert corrected[:3].isna().all()
    # Decision 4 Jan (delivers 5 Jan): only delivery days <= 2 Jan are used -> error 100.
    assert corrected[pd.Timestamp("2026-01-05T12:00Z")] == 1000 - 100
    # Decision 5 Jan delivers 6 Jan, whose error is huge (99999): it must never see its own day.
    assert corrected[pd.Timestamp("2026-01-06T12:00Z")] == 1000 - (100 + 200) / 2
    # Decision 6 Jan may use delivery days <= 4 Jan, still excluding the 99999 day (6 Jan).
    assert corrected[pd.Timestamp("2026-01-07T12:00Z")] == 1000 - (100 + 200 + 300) / 3
