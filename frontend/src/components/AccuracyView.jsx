import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { accuracyUrl, decisionTimesUrl } from '../api'
import { londonDateTime, londonDay, londonTime, longDate, mw, percent, shortDate, signedMw } from '../format'
import { useChartColors } from '../theme'
import { useApi } from '../useApi'
import ChartTooltip from './ChartTooltip'
import Notice from './Notice'
import StatTile from './StatTile'

const kiloTick = (v) => (v === 0 ? '0' : `${v / 1000}k`)

// Retrospective evaluation: selected forecasts scored against actual generation.
export default function AccuracyView({ meta, decisionTime, range, onRangeChange, onSelectDay }) {
  const reversed = range.start > range.end
  const { data, error, loading } = useApi(reversed ? null : accuracyUrl(decisionTime, range.start, range.end))

  return (
    <section aria-labelledby="accuracy-heading">
      <RangeControls meta={meta} range={range} onRangeChange={onRangeChange} />

      {reversed && (
        <Notice tone="error" title="Check the date range.">
          The first decision date must be on or before the last.
        </Notice>
      )}
      {error && (
        <Notice tone="error" title="Could not load accuracy.">
          {error.message}
        </Notice>
      )}
      {!data && loading && (
        <p className="muted" role="status">
          Loading accuracy…
        </p>
      )}
      {data && !reversed && <AccuracyDetail data={data} stale={loading} onSelectDay={onSelectDay} />}
      {!reversed && <DecisionTimeTable range={range} decisionTime={decisionTime} />}
    </section>
  )
}

function RangeControls({ meta, range, onRangeChange }) {
  const first = meta.first_decision_date
  const last = meta.last_decision_date
  const inJanuary = (v) => v >= first && v <= last
  const whole = range.start === first && range.end === last
  return (
    <fieldset className="controls">
      <legend className="sr-only">Decision dates to evaluate</legend>
      <label>
        First decision date
        <input
          type="date"
          value={range.start}
          min={first}
          max={last}
          onChange={(e) => inJanuary(e.target.value) && onRangeChange({ ...range, start: e.target.value })}
        />
      </label>
      <label>
        Last decision date
        <input
          type="date"
          value={range.end}
          min={first}
          max={last}
          onChange={(e) => inJanuary(e.target.value) && onRangeChange({ ...range, end: e.target.value })}
        />
      </label>
      <button type="button" disabled={whole} onClick={() => onRangeChange({ start: first, end: last })}>
        All of January
      </button>
    </fieldset>
  )
}

function AccuracyDetail({ data, stale, onSelectDay }) {
  const p = data.pooled
  const days = data.days.map((d) => ({ ...d, label: shortDate(d.delivery_date) }))
  const unmatched = p.expected_intervals - p.matched_intervals
  const span =
    data.start_date === data.end_date
      ? `the decision on ${longDate(data.start_date)}`
      : `decisions ${shortDate(data.start_date)} to ${shortDate(data.end_date)}`

  return (
    <div className={stale ? 'stale' : undefined} aria-busy={stale}>
      <h2 id="accuracy-heading">
        How accurate were the forecasts? ({span}, {data.decision_time} Europe/London)
      </h2>
      <Notice tone="info" title="Actuals are retrospective.">
        Actual generation was only known after each delivery day. It is used here to score the forecast that was
        selected at the cutoff, never to choose it.
      </Notice>

      {p.matched_intervals === 0 ? (
        <Notice tone="empty" title="Nothing to score.">
          No hour in this range has both a selected forecast and an actual value, so the metrics are unavailable rather
          than zero.
        </Notice>
      ) : (
        unmatched > 0 && (
          <Notice tone="partial" title="Partial data.">
            {unmatched} of {p.expected_intervals} hours lack a forecast or an actual ({p.forecast_intervals} with a
            forecast, {p.actual_intervals} with an actual). The metrics use only the {p.matched_intervals} matched hours.
          </Notice>
        )
      )}

      <div className="stat-row">
        <StatTile label="MAE" value={mw(p.mae_mw)} hint="typical size of a miss" />
        <StatTile label="RMSE" value={mw(p.rmse_mw)} hint="weights large misses more" />
        <StatTile label="Bias (mean error)" value={signedMw(p.bias_mw)} hint="+ = forecast too high" />
        <StatTile
          label="Middle 80% of errors"
          value={p.p10_mw == null ? '—' : `${signedMw(p.p10_mw)} to ${signedMw(p.p90_mw)}`}
          hint="10th to 90th percentile"
        />
        <StatTile
          label="Matched intervals"
          value={`${p.matched_intervals} / ${p.expected_intervals}`}
          hint={`${percent(p.matched_coverage)} of expected hours`}
          meter={p.matched_coverage}
        />
      </div>

      <MetricGuide errorDefinition={data.error_definition} />

      {p.matched_intervals > 0 && <ActualVsForecastChart intervals={data.intervals} />}
      {days.length > 1 && <DailyBiasChart days={days} onSelectDay={onSelectDay} />}

      <details open={days.length <= 3}>
        <summary>Daily accuracy table</summary>
        <DailyTable days={days} onSelectDay={onSelectDay} />
      </details>
    </div>
  )
}

function MetricGuide({ errorDefinition }) {
  return (
    <dl className="metric-guide">
      <div>
        <dt>Error sign</dt>
        <dd>
          {errorDefinition}. A positive error means the forecast was <strong>above</strong> actual generation.
        </dd>
      </div>
      <div>
        <dt>MAE</dt>
        <dd>Mean absolute error: the average size of the miss, ignoring direction.</dd>
      </div>
      <div>
        <dt>RMSE</dt>
        <dd>Root mean squared error: like MAE, but large misses count more. RMSE ≥ MAE.</dd>
      </div>
      <div>
        <dt>Bias</dt>
        <dd>Mean error: a systematic lean. Near 0 means misses cancel out on average.</dd>
      </div>
      <div>
        <dt>Middle 80% of errors</dt>
        <dd>8 in 10 matched hours had an error between these two values (10th and 90th percentiles).</dd>
      </div>
    </dl>
  )
}

// X-axis ticks: one per day (thinned to about 10); for a single day, every 3 hours.
function dayTicks(rows) {
  const midnights = rows.filter((r) => londonTime(r.target_time) === '00:00').map((r) => r.target_time)
  if (midnights.length <= 1) return rows.filter((_, i) => i % 3 === 0).map((r) => r.target_time)
  const step = Math.max(1, Math.ceil(midnights.length / 10))
  return midnights.filter((_, i) => i % step === 0)
}

// Round 5,000 MW gridlines from 0 up to just above the largest value.
function mwTicks(intervals) {
  const values = intervals.flatMap((i) => [i.forecast_mw, i.actual_mw]).filter((v) => v != null)
  const top = Math.max(5000, Math.ceil(Math.max(...values) / 5000) * 5000)
  return Array.from({ length: top / 5000 + 1 }, (_, k) => k * 5000)
}

function ActualVsForecastChart({ intervals }) {
  const colours = useChartColors()
  const ticks = dayTicks(intervals)
  const singleDay = intervals.filter((r) => londonTime(r.target_time) === '00:00').length <= 1
  const yTicks = mwTicks(intervals)
  return (
    <figure className="chart" aria-label="Hourly selected forecast compared with retrospective actual generation, in MW">
      <figcaption>
        Selected forecast vs actual generation, hourly (Europe/London, MW)
        <span className="legend">
          <span className="swatch" style={{ background: colours.forecast }} /> Selected forecast
          <span className="swatch" style={{ background: colours.actual }} /> Actual (retrospective)
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={intervals} margin={{ top: 12, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={colours.grid} vertical={false} />
          <XAxis
            dataKey="target_time"
            ticks={ticks}
            tickFormatter={(t) => (singleDay ? londonTime(t) : londonDay(t))}
            tickLine={false}
            stroke={colours.axis}
            tick={{ fill: colours.muted, fontSize: 12 }}
          />
          <YAxis
            width={48}
            ticks={yTicks}
            domain={[0, yTicks[yTicks.length - 1]]}
            tickLine={false}
            axisLine={false}
            tickFormatter={kiloTick}
            tick={{ fill: colours.muted, fontSize: 12 }}
          />
          <Tooltip
            cursor={{ stroke: colours.axis }}
            content={({ active, payload }) => {
              const i = payload?.[0]?.payload
              return (
                <ChartTooltip
                  active={active && i}
                  title={i && `${londonDateTime(i.target_time)} Europe/London`}
                  rows={
                    i && [
                      ['Forecast', mw(i.forecast_mw), colours.forecast],
                      ['Actual', mw(i.actual_mw), colours.actual],
                      ['Error', signedMw(i.error_mw)],
                      ['Published', londonDateTime(i.forecast_publish_time)],
                    ]
                  }
                />
              )
            }}
          />
          {[
            ['forecast_mw', colours.forecast, 'Selected forecast'],
            ['actual_mw', colours.actual, 'Actual'],
          ].map(([key, colour, name]) => (
            <Line
              key={key}
              dataKey={key}
              name={name}
              stroke={colour}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              activeDot={{ r: 4, stroke: colours.surface, strokeWidth: 2 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <p className="muted small">Gaps mean the forecast or actual for that hour is missing; nothing is filled in.</p>
    </figure>
  )
}

function DailyBiasChart({ days, onSelectDay }) {
  const colours = useChartColors()
  return (
    <figure className="chart" aria-label="Daily bias (mean error) by delivery day, in MW">
      <figcaption>
        Daily bias by delivery day (MW). Click a day to open its decision.
        <span className="legend">
          <span className="swatch" style={{ background: colours.over }} /> Over-forecast
          <span className="swatch" style={{ background: colours.under }} /> Under-forecast
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={days} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={colours.grid} vertical={false} />
          <XAxis dataKey="label" interval="preserveStartEnd" tickLine={false} stroke={colours.axis} tick={{ fill: colours.muted, fontSize: 12 }} />
          <YAxis width={48} tickLine={false} axisLine={false} tickFormatter={kiloTick} tick={{ fill: colours.muted, fontSize: 12 }} />
          <ReferenceLine y={0} stroke={colours.axis} />
          <Tooltip
            cursor={{ fill: colours.grid, opacity: 0.5 }}
            content={({ active, payload }) => {
              const d = payload?.[0]?.payload
              return (
                <ChartTooltip
                  active={active && d}
                  title={d && `Delivery ${longDate(d.delivery_date)}`}
                  rows={
                    d && [
                      ['Bias', signedMw(d.bias_mw)],
                      ['MAE', mw(d.mae_mw)],
                      ['Matched', `${d.matched_intervals} of ${d.expected_intervals}`],
                    ]
                  }
                />
              )
            }}
          />
          <Bar
            dataKey="bias_mw"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
            cursor="pointer"
            onClick={(entry) => onSelectDay(entry.payload?.decision_date ?? entry.decision_date)}
          >
            {days.map((d) => (
              <Cell
                key={d.decision_date}
                fill={d.bias_mw == null ? colours.muted : d.bias_mw >= 0 ? colours.over : colours.under}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}

function DailyTable({ days, onSelectDay }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">Daily accuracy by decision date</caption>
        <thead>
          <tr>
            <th scope="col">Decision date</th>
            <th scope="col">Delivery date</th>
            <th scope="col">MAE</th>
            <th scope="col">RMSE</th>
            <th scope="col">Bias</th>
            <th scope="col">Matched / expected</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.decision_date}>
              <td>
                <button type="button" className="link" onClick={() => onSelectDay(d.decision_date)}>
                  {shortDate(d.decision_date)}
                </button>
              </td>
              <td>{shortDate(d.delivery_date)}</td>
              <td>{mw(d.mae_mw)}</td>
              <td>{mw(d.rmse_mw)}</td>
              <td>{signedMw(d.bias_mw)}</td>
              <td>
                {d.matched_intervals} / {d.expected_intervals}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Same decision dates, different decision times: does a later cutoff (fresher forecast) help?
function DecisionTimeTable({ range, decisionTime }) {
  const { data, error, loading } = useApi(decisionTimesUrl(range.start, range.end))
  return (
    <section className="decision-times" aria-labelledby="decision-times-heading">
      <h3 id="decision-times-heading">Does deciding later help?</h3>
      <p className="muted">
        The same decision dates scored at different decision times (Europe/London). A later time can use fresher
        forecasts; whether it is possible depends on the market timetable, which is not modelled here. All times are
        assumptions.
      </p>
      {error && (
        <Notice tone="error" title="Could not load the comparison.">
          {error.message}
        </Notice>
      )}
      {!data && loading && (
        <p className="muted" role="status">
          Loading comparison…
        </p>
      )}
      {data && (
        <div className={`table-scroll${loading ? ' stale' : ''}`}>
          <table>
            <caption className="sr-only">Accuracy of the selected forecasts by decision time</caption>
            <thead>
              <tr>
                <th scope="col">Decision time</th>
                <th scope="col">Forecast coverage</th>
                <th scope="col">MAE</th>
                <th scope="col">RMSE</th>
                <th scope="col">Bias</th>
                <th scope="col">P90 miss</th>
              </tr>
            </thead>
            <tbody>
              {data.decision_times.map((r) => {
                const current = r.decision_time === decisionTime
                return (
                  <tr key={r.decision_time} className={current ? 'current-row' : undefined} aria-current={current || undefined}>
                    <td>
                      {r.decision_time}
                      {current && <span className="sr-only"> (selected)</span>}
                    </td>
                    <td>{percent(r.forecast_coverage)}</td>
                    <td>{mw(r.mae_mw)}</td>
                    <td>{mw(r.rmse_mw)}</td>
                    <td>{signedMw(r.bias_mw)}</td>
                    <td>{mw(r.p90_abs_error_mw)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
