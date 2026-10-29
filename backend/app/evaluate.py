"""Evaluation of the selected WINDFOR forecasts: extended metrics, a naive baseline, breakdowns.

Run from the repository root:
    python -m backend.app.evaluate                  # 10:00 decision time, all of January
    python -m backend.app.evaluate --decision-time 16:00

Prints Markdown tables (used for docs/evaluation.md). Everything is retrospective:
actuals score forecasts and never choose or adjust them. The persistence baseline
uses only actuals that had been *published* by each decision cutoff.
"""

from __future__ import annotations

import argparse
from datetime import date, time, timedelta

import numpy as np
import pandas as pd

from . import analysis

WITHIN_MW = (1000, 2000)


# ---------------------------------------------------------------- metrics


def extended_metrics(forecast: pd.Series, actual: pd.Series) -> dict:
    """Metrics over matched pairs only (both values present). None when there are none.

    mae, rmse, bias           MW; error = forecast - actual
    median_error              MW, robust centre of the errors
    nmae_pct                  MAE as % of mean actual over the same hours
    wape_pct                  sum|error| / sum(actual) * 100 (no division by near-zero hours, unlike MAPE)
    p90_abs_error             MW: 90% of hours missed by less than this
    within_1gw_pct/_2gw_pct   share of hours with |error| <= 1 / 2 GW
    over_forecast_pct         share of hours with error > 0
    """
    pairs = pd.DataFrame({"f": forecast, "a": actual}).dropna()
    keys = [
        "n", "mae_mw", "rmse_mw", "bias_mw", "median_error_mw", "nmae_pct", "wape_pct",
        "p90_abs_error_mw", "within_1gw_pct", "within_2gw_pct", "over_forecast_pct",
    ]
    if pairs.empty:
        return {**dict.fromkeys(keys), "n": 0}
    e = (pairs["f"] - pairs["a"]).to_numpy(dtype=float)
    a = pairs["a"].to_numpy(dtype=float)
    abs_e = np.abs(e)
    mae = float(abs_e.mean())
    return {
        "n": int(e.size),
        "mae_mw": mae,
        "rmse_mw": float(np.sqrt(np.mean(e**2))),
        "bias_mw": float(e.mean()),
        "median_error_mw": float(np.median(e)),
        "nmae_pct": float(100 * mae / a.mean()) if a.mean() else None,
        "wape_pct": float(100 * abs_e.sum() / a.sum()) if a.sum() else None,
        "p90_abs_error_mw": float(np.percentile(abs_e, 90)),
        "within_1gw_pct": float(100 * np.mean(abs_e <= WITHIN_MW[0])),
        "within_2gw_pct": float(100 * np.mean(abs_e <= WITHIN_MW[1])),
        "over_forecast_pct": float(100 * np.mean(e > 0)),
    }


def skill_score(mae_model: float | None, mae_baseline: float | None) -> float | None:
    """1 - MAE_model / MAE_baseline. 1 = perfect, 0 = no better than baseline, < 0 = worse."""
    if mae_model is None or not mae_baseline:
        return None
    return 1 - mae_model / mae_baseline


# ---------------------------------------------------------------- baseline


persistence_value = analysis.persistence_value  # shared with the API


def hourly_table(actuals: pd.DataFrame, forecasts: pd.DataFrame, dates: list[date], cutoff: time) -> pd.DataFrame:
    """One row per delivery hour: forecast, persistence baseline, actual, lead time, labels."""
    hours = analysis.accuracy(actuals, forecasts, dates, cutoff)["hours"].copy()
    baseline = {d: persistence_value(actuals, d, cutoff) for d in dates}
    hours["persistence_mw"] = hours["decision_date"].map(baseline)
    local = hours.index.tz_convert(analysis.LONDON)
    hours["hour_of_day"] = local.hour
    hours["delivery_date"] = local.date
    return hours


# ---------------------------------------------------------------- breakdowns


def breakdown(hours: pd.DataFrame, by: str | pd.Series, label: str) -> pd.DataFrame:
    """Extended metrics of the selected forecast for each group."""
    rows = []
    for key, group in hours.groupby(by, observed=True, sort=True):
        rows.append({label: key, **extended_metrics(group["forecast_mw"], group["actual_mw"])})
    return pd.DataFrame(rows)


def lead_time_bucket(lead_hours: pd.Series) -> pd.Series:
    return pd.cut(lead_hours, bins=[0, 18, 24, 30, 36, 48], right=False,
                  labels=["<18 h", "18-24 h", "24-30 h", "30-36 h", ">=36 h"])


actual_level_bucket = analysis.wind_level  # shared with the API


# ---------------------------------------------------------------- what-if (not used by the app)


def rolling_bias_correction(hours: pd.DataFrame, window_days: int = 7) -> pd.Series:
    """WHAT-IF ONLY: forecast minus the mean error of recent, fully known delivery days.

    For decision date D, only delivery days up to D-2 are used (they ended at least
    24 h before D began), so every actual used was published before any cutoff on D. No look-ahead. NaN when no
    history is available yet. The app never applies this; it reports raw forecasts.
    """
    daily_error = hours.groupby("delivery_date")["error_mw"].mean()
    corrected = pd.Series(np.nan, index=hours.index)
    for decision, group in hours.groupby("decision_date"):
        latest_known = decision - timedelta(days=1)  # delivery day D-1 ended at the start of D; use D-2 and earlier
        history = daily_error[[d for d in daily_error.index if d < latest_known]].dropna().tail(window_days)
        if len(history):
            corrected[group.index] = group["forecast_mw"] - history.mean()
    return corrected


# ---------------------------------------------------------------- report


def _fmt(v, digits=0):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:,.{digits}f}"


def report(decision_time: time, dates: list[date]) -> str:
    actuals, forecasts = analysis.load_data()
    hours = hourly_table(actuals, forecasts, dates, decision_time)
    out = [f"## Evaluation at {decision_time:%H:%M} Europe/London, decisions {dates[0]} to {dates[-1]}", ""]

    # Headline + baseline on the common sample (hours where forecast, baseline and actual all exist).
    common = hours.dropna(subset=["forecast_mw", "persistence_mw", "actual_mw"])
    f = extended_metrics(hours["forecast_mw"], hours["actual_mw"])
    fc = extended_metrics(common["forecast_mw"], common["actual_mw"])
    pc = extended_metrics(common["persistence_mw"], common["actual_mw"])
    out += ["| Metric | Selected forecast (all matched hours) | Forecast (common sample) | Persistence baseline (common sample) |",
            "|---|---|---|---|"]
    for key, name, d in [("n", "Hours", 0), ("mae_mw", "MAE (MW)", 0), ("rmse_mw", "RMSE (MW)", 0),
                         ("bias_mw", "Bias (MW)", 0), ("median_error_mw", "Median error (MW)", 0),
                         ("nmae_pct", "nMAE (% of mean actual)", 1), ("wape_pct", "WAPE (%)", 1),
                         ("p90_abs_error_mw", "P90 absolute error (MW)", 0),
                         ("within_1gw_pct", "Hours within ±1 GW (%)", 1), ("within_2gw_pct", "Hours within ±2 GW (%)", 1),
                         ("over_forecast_pct", "Hours over-forecast (%)", 1)]:
        out.append(f"| {name} | {_fmt(f[key], d)} | {_fmt(fc[key], d)} | {_fmt(pc[key], d)} |")
    skill = skill_score(fc["mae_mw"], pc["mae_mw"])
    out += ["", f"MAE skill vs persistence (common sample): **{_fmt(None if skill is None else 100 * skill, 1)}%**", ""]
    spread = np.sqrt(max(f["rmse_mw"] ** 2 - f["bias_mw"] ** 2, 0))
    out += [f"Error decomposition: RMSE² = bias² + spread². Bias share of squared error: "
            f"**{_fmt(100 * f['bias_mw'] ** 2 / f['rmse_mw'] ** 2, 0)}%**; spread (std of error): {_fmt(spread)} MW.", ""]

    # What-if: rolling bias correction (not part of the app), compared on the same hours.
    hours = hours.assign(corrected_mw=rolling_bias_correction(hours))
    both = hours.dropna(subset=["forecast_mw", "corrected_mw", "actual_mw"])
    raw, cor = (extended_metrics(both[c], both["actual_mw"]) for c in ("forecast_mw", "corrected_mw"))
    out += ["### What-if: 7-day rolling bias correction (not applied in the app)", "",
            "| Metric | Raw selected forecast | Bias-corrected (what-if) |", "|---|---|---|"]
    for key, name, d in [("n", "Hours", 0), ("mae_mw", "MAE (MW)", 0), ("rmse_mw", "RMSE (MW)", 0),
                         ("bias_mw", "Bias (MW)", 0), ("p90_abs_error_mw", "P90 absolute error (MW)", 0),
                         ("within_1gw_pct", "Hours within ±1 GW (%)", 1)]:
        out.append(f"| {name} | {_fmt(raw[key], d)} | {_fmt(cor[key], d)} |")
    out.append("")

    for title, table in [
        ("By lead time (hours from publication to target hour)", breakdown(hours, lead_time_bucket(hours["lead_time_hours"]), "lead time")),
        ("By hour of day (Europe/London)", breakdown(hours, (hours["hour_of_day"] // 6 * 6).map(lambda h: f"{h:02d}-{h + 5:02d}h"), "hours")),
        ("By actual wind level", breakdown(hours, actual_level_bucket(hours["actual_mw"]), "actual level")),
    ]:
        out += [f"### {title}", "", f"| Group | Hours | MAE | Bias | P90 abs | Within ±1 GW % |", "|---|---|---|---|---|---|"]
        for _, r in table.iterrows():
            out.append(f"| {r.iloc[0]} | {r['n']} | {_fmt(r['mae_mw'])} | {_fmt(r['bias_mw'])} | {_fmt(r['p90_abs_error_mw'])} | {_fmt(r['within_1gw_pct'], 1)} |")
        out.append("")

    days = breakdown(hours, "delivery_date", "delivery day")
    out += ["### Daily bias", "",
            f"- Delivery days with positive bias (over-forecast): **{int((days['bias_mw'] > 0).sum())} of {len(days)}**",
            f"- Worst days by MAE: " + ", ".join(f"{r['delivery day']} ({_fmt(r['mae_mw'])} MW)" for _, r in days.nlargest(3, 'mae_mw').iterrows()),
            f"- Best days by MAE: " + ", ".join(f"{r['delivery day']} ({_fmt(r['mae_mw'])} MW)" for _, r in days.nsmallest(3, 'mae_mw').iterrows()),
            ""]
    return "\n".join(out)


def cutoff_comparison(dates: list[date], cutoffs: list[str]) -> str:
    actuals, forecasts = analysis.load_data()
    out = ["## Decision time comparison", "", "| Decision time | Forecast coverage | MAE | RMSE | Bias | P90 abs | Skill vs persistence |",
           "|---|---|---|---|---|---|---|"]
    for c in cutoffs:
        cut = analysis.parse_cutoff(c)
        h = hourly_table(actuals, forecasts, dates, cut)
        m = extended_metrics(h["forecast_mw"], h["actual_mw"])
        common = h.dropna(subset=["forecast_mw", "persistence_mw", "actual_mw"])
        s = skill_score(extended_metrics(common["forecast_mw"], common["actual_mw"])["mae_mw"],
                        extended_metrics(common["persistence_mw"], common["actual_mw"])["mae_mw"])
        cov = h["forecast_mw"].notna().mean() * 100
        out.append(f"| {c} | {cov:.1f}% | {_fmt(m['mae_mw'])} | {_fmt(m['rmse_mw'])} | {_fmt(m['bias_mw'])} | "
                   f"{_fmt(m['p90_abs_error_mw'])} | {_fmt(None if s is None else 100 * s, 1)}% |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the selected WINDFOR forecasts for January 2026.")
    parser.add_argument("--decision-time", default=analysis.DEFAULT_CUTOFF.strftime("%H:%M"), help="HH:MM, Europe/London")
    args = parser.parse_args(argv)
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(31)]
    print(report(analysis.parse_cutoff(args.decision_time), dates))
    print()
    print(cutoff_comparison(dates, ["00:00", "02:30", "06:00", "10:00", "12:30", "16:00", "20:00"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
