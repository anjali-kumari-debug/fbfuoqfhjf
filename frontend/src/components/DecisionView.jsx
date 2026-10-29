import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { forecastUrl } from '../api'
import { addDays, londonDateTime, londonTime, longDate, mw, percent, signedMw } from '../format'
import { useChartColors } from '../theme'
import { useApi } from '../useApi'
import ChartTooltip from './ChartTooltip'
import StatTile from './StatTile'

export default function DecisionView({ meta, date, onDateChange, cutoff }) {
  const { data, error, loading } = useApi(forecastUrl(date, cutoff))
  const first = meta.first_decision_date
  const last = meta.last_decision_date

  return (
    <section>
      <div className="controls">
        <label>
          Decision date
          <input
            type="date"
            value={date}
            min={first}
            max={last}
            onChange={(e) => e.target.value && onDateChange(e.target.value)}
          />
        </label>
        <button type="button" onClick={() => onDateChange(addDays(date, -1))} disabled={date <= first}>
          ← Previous day
        </button>
        <button type="button" onClick={() => onDateChange(addDays(date, 1))} disabled={date >= last}>
          Next day →
        </button>
      </div>

      {error && <p className="error">Could not load this decision: {error.message}</p>}
      {data && <DecisionDetail data={data} stale={loading} />}
      {!data && loading && <p className="muted">Loading…</p>}
    </section>
  )
}

function DecisionDetail({ data, stale }) {
  const forecasts = data.intervals.filter((h) => h.forecast_mw != null)
  const lowest = forecasts.reduce((a, b) => (b.forecast_mw < a.forecast_mw ? b : a), forecasts[0])
  const mean = forecasts.length ? forecasts.reduce((s, h) => s + h.forecast_mw, 0) / forecasts.length : null
  const { coverage, metrics } = data

  return (
    <div className={stale ? 'stale' : undefined}>
      <h2>
        Decision on {longDate(data.decision_date)} at {data.decision_time} → delivery on{' '}
        {longDate(data.delivery_date)}
      </h2>

      <h3>At the cutoff: what the trader could see</h3>
      <p className="muted">
        {data.publish_times_used.length === 0
          ? 'No forecast had been published by the cutoff.'
          : `Forecast published ${data.publish_times_used.map(londonDateTime).join(', ')} (London time), the latest available at or before the cutoff.`}
      </p>
      <div className="stat-row">
        <StatTile label="Average forecast" value={mw(mean)} />
        <StatTile
          label="Lowest forecast hour"
          value={mw(lowest?.forecast_mw)}
          hint={lowest ? `at ${londonTime(lowest.target_time)}` : undefined}
        />
        <StatTile
          label="Forecast coverage"
          value={percent(coverage.forecast_coverage)}
          hint={`${coverage.forecast_intervals} of ${coverage.expected_intervals} hours`}
        />
      </div>

      <h3>Afterwards: how the forecast turned out</h3>
      <p className="muted">Actual generation is only known after delivery. It is used to score the forecast, never to choose it.</p>
      <div className="stat-row">
        <StatTile label="MAE" value={mw(metrics.mae_mw)} hint="typical size of the miss" />
        <StatTile label="Bias (mean error)" value={signedMw(metrics.bias_mw)} hint="+ means over-forecast" />
        <StatTile label="RMSE" value={mw(metrics.rmse_mw)} hint="penalises large misses" />
        <StatTile
          label="Scored hours"
          value={percent(coverage.matched_coverage)}
          hint={`${coverage.matched_intervals} of ${coverage.expected_intervals} hours have both`}
        />
      </div>

      <ForecastActualChart hours={data.intervals} />

      <details>
        <summary>Show hourly table</summary>
        <HourlyTable hours={data.intervals} />
      </details>
    </div>
  )
}

function ForecastActualChart({ hours }) {
  const colours = useChartColors()
  const rows = hours.map((h) => ({ ...h, label: londonTime(h.target_time) }))
  const lastRow = rows[rows.length - 1]
  // Push the two end labels apart so they never overlap.
  const forecastOnTop = (lastRow?.forecast_mw ?? 0) >= (lastRow?.actual_mw ?? 0)

  const endLabel = (text, above) =>
    function EndLabel({ x, y, index }) {
      if (index !== rows.length - 1 || y == null) return null
      return (
        <text x={x + 8} y={y} dy={above ? -4 : 12} className="end-label">
          {text}
        </text>
      )
    }

  return (
    <figure className="chart">
      <figcaption>
        Hourly wind generation, delivery day (London time, MW)
        <span className="legend">
          <span className="swatch" style={{ background: colours.forecast }} /> Forecast
          <span className="swatch" style={{ background: colours.actual }} /> Actual (mean of two half-hours)
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={rows} margin={{ top: 16, right: 72, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={colours.grid} vertical={false} />
          <XAxis
            dataKey="label"
            interval={2}
            tickLine={false}
            stroke={colours.axis}
            tick={{ fill: colours.muted, fontSize: 12 }}
          />
          <YAxis
            width={56}
            tickLine={false}
            axisLine={false}
            tick={{ fill: colours.muted, fontSize: 12 }}
            tickFormatter={(v) => v.toLocaleString('en-GB')}
          />
          <Tooltip
            cursor={{ stroke: colours.axis }}
            content={({ active, payload }) => {
              const h = payload?.[0]?.payload
              return (
                <ChartTooltip
                  active={active && h}
                  title={h && `${h.label} London`}
                  rows={
                    h && [
                      ['Forecast', mw(h.forecast_mw), colours.forecast],
                      ['Actual', mw(h.actual_mw), colours.actual],
                      ['Error', signedMw(h.error_mw)],
                      ['Published', londonDateTime(h.forecast_publish_time)],
                    ]
                  }
                />
              )
            }}
          />
          <Line
            dataKey="forecast_mw"
            name="Forecast"
            stroke={colours.forecast}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: colours.surface, strokeWidth: 2 }}
            isAnimationActive={false}
            label={endLabel('Forecast', forecastOnTop)}
          />
          <Line
            dataKey="actual_mw"
            name="Actual"
            stroke={colours.actual}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: colours.surface, strokeWidth: 2 }}
            isAnimationActive={false}
            label={endLabel('Actual', !forecastOnTop)}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="muted small">Gaps in a line mean the data is missing; missing values are never filled in.</p>
    </figure>
  )
}

function HourlyTable({ hours }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Hour (London)</th>
          <th>Forecast</th>
          <th>Actual</th>
          <th>Error</th>
          <th>Published</th>
          <th>Hours ahead</th>
        </tr>
      </thead>
      <tbody>
        {hours.map((h) => (
          <tr key={h.target_time}>
            <td>{londonTime(h.target_time)}</td>
            <td>{mw(h.forecast_mw)}</td>
            <td>{mw(h.actual_mw)}</td>
            <td>{signedMw(h.error_mw)}</td>
            <td>{londonDateTime(h.forecast_publish_time)}</td>
            <td>{h.lead_time_hours ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
