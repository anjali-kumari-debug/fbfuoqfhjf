# Forecast evaluation: January 2026 decisions

This document defines the evaluation metrics, evaluates the wind forecast used in
the app, and suggests improvements.

The "model" evaluated here is **NESO's WINDFOR forecast**, published through Elexon
BMRS. This project does not build its own forecasting model; it measures how good
the forecast available at each decision time turned out to be.

Reproduce every number below from the repository root:

```bash
python -m backend.app.evaluate                    # 10:00 decision time (default)
python -m backend.app.evaluate --decision-time 16:00
```

Tests for every metric are in `backend/tests/test_evaluate.py`.

## 1. Setup

| Item | Definition |
|---|---|
| Decisions | Every day of January 2026 (31), at a decision time of 10:00 Europe/London (a demo assumption) |
| Delivery | The next Europe/London calendar day, 24 hourly intervals (744 in total) |
| Forecast `F` | For each hour, the WINDFOR value with the latest `publishTime` at or before the cutoff |
| Actual `A` | FUELHH WIND: the mean of the hour's two half-hours. Missing if either half-hour is missing |
| Error | `e = F − A` (MW). Positive means over-forecast |
| Sample | **Matched hours only** (both `F` and `A` present). Nothing is filled in; coverage is reported separately |
| Scope | Wind farms with operational metering on the transmission network (about 82% of GB wind). Not total GB wind |

## 2. Metric definitions

| Metric | Formula | Why it is useful to a buying team |
|---|---|---|
| **MAE** | mean(\|e\|) | The typical size of a miss, in MW |
| **RMSE** | √mean(e²) | Penalises large misses, which are the costly ones. RMSE ≫ MAE means heavy tails |
| **Bias** (mean error) | mean(e) | A systematic lean. Positive means wind was over-promised, so you would have under-bought |
| **Median error** | median(e) | The centre of the errors, not distorted by a few extreme hours |
| **nMAE** | MAE / mean(A) × 100 | A scale-free size of the miss |
| **WAPE** | Σ\|e\| / ΣA × 100 | Like a percentage error, but stable when wind is near zero (**MAPE is not used** because it divides by near-zero actuals) |
| **P90 absolute error** | 90th percentile of \|e\| | "9 hours in 10, the miss was below X MW": a risk-sizing number |
| **Hit rate** | % of hours with \|e\| ≤ 1 GW (and ≤ 2 GW) | An easy-to-explain reliability number |
| **Over-forecast share** | % of hours with e > 0 | Shows whether the bias is persistent or driven by a few hours |
| **Skill vs persistence** | 1 − MAE_forecast / MAE_persistence | Does the forecast beat a naive rule? 1 is perfect, 0 is no better, < 0 is worse |
| **Error decomposition** | RMSE² = bias² + spread² | How much of the error is a constant offset (fixable) and how much is random |
| **Coverage** | expected / with forecast / with actual / matched intervals | Shows whether data was missing; reported separately, never hidden |

**Persistence baseline:** "the last actual half-hour **published** by the cutoff
will continue for the whole delivery day". It uses only information the trader
really had at the cutoff, so it has no look-ahead (tested).

Forecast and baseline are compared on the **same hours**. The processed actuals
start on 2 Jan, so the 1 Jan decision has no baseline value, leaving 720 hours.

## 3. Results at the 10:00 decision time

| Metric | Selected forecast (744 h) | Forecast, common sample (720 h) | Persistence (720 h) |
|---|---|---|---|
| MAE | **2,013 MW** | 1,974 MW | 4,175 MW |
| RMSE | 2,506 MW | 2,477 MW | 5,422 MW |
| Bias | **+1,730 MW** | +1,681 MW | +2 MW |
| Median error | +1,560 MW | +1,461 MW | +57 MW |
| nMAE / WAPE | 17.8% | 17.7% | 37.4% |
| P90 absolute error | 4,144 MW | 4,150 MW | 8,858 MW |
| Hours within ±1 GW | 27.7% | 28.6% | 24.2% |
| Hours within ±2 GW | 59.7% | 61.7% | 36.4% |
| Hours over-forecast | **84.3%** | 83.8% | 50.8% |

- **Skill vs persistence: +52.7%.** The forecast roughly halves the error of the
  naive rule, so it clearly adds value.
- **Error decomposition: 48% of the squared error is the constant bias.** The
  remaining random spread is 1,813 MW.
- **Coverage:** 744 of 744 hours were matched at 10:00.

### Breakdowns (10:00 decision time)

| Lead time (publish → hour) | Hours | MAE | Bias | P90 abs |
|---|---|---|---|---|
| < 18 h | 124 | 2,207 | 2,157 | 4,396 |
| 18–24 h | 186 | 2,199 | 2,099 | 4,768 |
| 24–30 h | 186 | 1,878 | 1,412 | 3,673 |
| 30–36 h | 186 | 1,875 | 1,389 | 4,091 |
| ≥ 36 h | 62 | 1,886 | 1,747 | 4,212 |

| Hour of day (London) | MAE | Bias | Within ±1 GW |
|---|---|---|---|
| 00–05 | 2,264 | 2,206 | 22.6% |
| 06–11 | 2,044 | 1,872 | 31.7% |
| 12–17 | 1,864 | 1,304 | 23.7% |
| 18–23 | 1,881 | 1,537 | 32.8% |

| Actual wind level | Hours | MAE | Bias | Within ±1 GW |
|---|---|---|---|---|
| < 5 GW | 62 | 2,153 | 2,071 | 21.0% |
| 5–10 GW | 245 | 1,627 | 1,137 | 34.3% |
| 10–15 GW | 247 | 2,164 | 1,884 | 32.8% |
| ≥ 15 GW | 190 | 2,269 | 2,183 | 14.7% |

- **Daily bias:** 28 of 31 delivery days were over-forecast.
- **Worst days by MAE:** 28 Jan (5,375 MW), 12 Jan (4,901), 11 Jan (4,897).
- **Best days by MAE:** 9 Jan (797), 19 Jan (816), 1 Feb (854).

### Effect of the decision time

| Decision time | Coverage | MAE | RMSE | Bias | P90 abs | Skill vs persistence |
|---|---|---|---|---|---|---|
| 00:00 | 91.7% | 2,119 | 2,590 | 1,794 | 4,196 | 55.5% |
| 02:30 | 100% | 2,073 | 2,578 | 1,735 | 4,249 | 56.4% |
| 06:00 | 100% | 2,016 | 2,521 | 1,671 | 4,158 | 55.7% |
| 10:00 | 100% | 2,013 | 2,506 | 1,730 | 4,144 | 52.7% |
| 12:30 | 100% | 1,904 | 2,361 | 1,692 | 3,847 | 52.5% |
| 16:00 | 100% | 1,873 | 2,327 | 1,709 | 3,781 | 49.3% |
| 20:00 | 100% | 1,874 | 2,326 | 1,692 | 3,745 | 41.1% |

## 4. Interpretation

1. **The forecast is useful.** It beats persistence by about 50% on MAE at every
   decision time.
2. **The dominant problem is a persistent over-forecast, not noise.** The bias is
   about +1.7 GW (15% of mean output). 84% of hours and 28 of 31 days were
   over-forecast, and the bias accounts for about half of the squared error. For a
   buyer, relying on the raw forecast would usually have meant **buying too
   little** other generation.
3. **Waiting helps a little, but doesn't fix the bias.** Moving from 10:00 to 16:00
   cuts MAE by about 7% (2,013 → 1,873 MW) and P90 by about 9%. The bias stays
   around +1.7 GW at every decision time, so it is **not** caused by how old the
   forecast is.
4. **Lead time and hour of day are mixed together.** With a fixed decision time,
   the shortest lead times are always the night hours (00–05). Their higher error
   reflects night-time bias, not shorter lead time being worse. The
   decision-time comparison above is the cleaner view of forecast age.
5. **High-wind hours are the hardest to hit closely.** Only 15% of hours above
   15 GW were within ±1 GW, although their MAE is similar to other levels. Low-wind
   hours (< 5 GW) are also strongly over-forecast.
6. **The cause of the bias is unverified.** Possible explanations include
   curtailment of wind farms for grid reasons (which lowers metered output) and
   differences in what the two datasets cover. The data here cannot separate them.

### What-if: removing the known bias (analysis only, not applied in the app)

Each decision's forecast minus the mean error of the previous 7 delivery days,
using only days that ended at least 24 hours before the decision date (no
look-ahead, tested). Compared on the same 672 hours:

| Metric | Raw selected forecast | Bias-corrected (what-if) |
|---|---|---|
| MAE | 2,008 MW | **1,660 MW (−17%)** |
| RMSE | 2,515 MW | 2,072 MW (−18%) |
| Bias | +1,695 MW | −11 MW |
| P90 absolute error | 4,292 MW | 3,339 MW (−22%) |
| Hours within ±1 GW | 28.0% | 37.9% |

This shows that the bias is **stable enough to be learned from recent history**.
It is shown as evidence for the suggestions below. The app deliberately reports
the raw forecast, because adjusting forecasts is outside this pilot's scope
(CLAUDE.md: no ML forecasting; actuals are evaluation-only).

## 5. Suggested improvements

### For the trading team (how to use the numbers today)

Implemented in the app as quantified error at decision time, the purpose the
challenge states ("so that they can make their decisions considering the
quantified error"):

- **Decision view:** the recent bias, MAE and P90 miss over the previous 7
  decisions, using only actuals published by the cutoff. A shaded "likely
  actual range" band shows where actual output would fall in 8 of 10 hours if
  recent errors repeat. The forecast itself is never changed.
- **Accuracy view:** a "Does deciding later help?" table compares the same
  decision dates at seven decision times.

How to use them:

- **Treat the forecast as optimistic.** Over January it ran about 1.7 GW high in
  most hours. Plan cover against the forecast minus the recent bias, not the raw
  value.
- **Size buffers from P90, not MAE.** At 10:00 the miss was below about 4.1 GW in
  9 hours out of 10. Use the tail, by hour, for risk-sized cover.
- **If the market timetable allows, decide later.** A 16:00 cutoff reduces MAE by
  about 7% and P90 by about 9%.

### For the product (next iterations)

1. **Show a recent-bias band and P10–P90 error bands** on the decision chart,
   computed only from delivery days completed before the cutoff. This turns the
   accuracy view into decision support without changing the forecast itself.
2. **Show a persistence-skill card** in the accuracy view, so users see that the
   forecast clearly beats a naive rule.
3. **Add breakdowns by hour of day and wind level** to the accuracy view (the
   evaluation module already computes them).
4. **Make the decision time and range shareable in the URL**, so analysts can
   send a link to a specific view.
5. **Extend the data window to several months, including summer.** One winter
   month is a small sample, and the bias may be seasonal. The pipeline already
   takes `--decision-month`.

### For the analysis (if scope expands)

1. **Investigate the bias source:** compare against curtailment and constraint
   data (Elexon balancing data, a different dataset, so a scope change) and
   against embedded-wind estimates.
2. **Evaluate a simple, transparent correction** (rolling bias, or bias by hour of
   day and wind level) with walk-forward testing over several months before
   offering it as an option. The what-if above suggests a 15–20% gain.
3. **Report statistical uncertainty:** bootstrap confidence intervals over days
   for MAE and bias, so that differences such as 10:00 vs 16:00 can be judged.
4. **Add demand data** if the goal moves towards procurement volumes. This app
   deliberately does not size purchases.

## 6. Limitations

- One month (January 2026, winter) and 744 hours. The days are not independent,
  so treat the percentages as indicative.
- Metered transmission wind only (about 82% of GB wind).
- The hourly actual is the mean of two half-hours. It is unverified whether a
  WINDFOR value means an hourly average or the value at the start of the hour.
- The decision time is a demo assumption, not a market rule.
