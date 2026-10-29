import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { forecastUrl } from '../api'
import { addDays, londonDateTime, londonTime, longDate, mw, percent } from '../format'
import { useChartColors } from '../theme'
import { useApi } from '../useApi'
import ChartTooltip from './ChartTooltip'
import Notice from './Notice'
import StatTile from './StatTile'

// What the trader could know at the decision cutoff: forecasts only.
// Actuals are retrospective and appear in the accuracy view.
export default function DecisionView({ meta, date, onDateChange, decisionTime, onShowOutcome }) {
  const { data, error, loading } = useApi(forecastUrl(date, decisionTime))
  const first = meta.first_decision_date
  const last = meta.last_decision_date

  return (
    <section aria-labelledby="decision-heading">
      <div className="controls">
        <label>
          Decision date (January 2026)
          <input
            type="date"
            value={date}
            min={first}
            max={last}
            required
            onChange={(e) => e.target.value >= first && e.target.value <= last && onDateChange(e.target.value)}
          />
        </label>
        <button type="button" onClick={() => onDateChange(addDays(date, -1))} disabled={date <= first}>
          ← Previous day
        </button>
        <button type="button" onClick={() => onDateChange(addDays(date, 1))} disabled={date >= last}>
          Next day →
        </button>
      </div>

      {error && (
        <Notice tone="error" title="Could not load this decision.">
          {error.message}
        </Notice>
      )}
      {!data && loading && (
        <p className="muted" role="status">
          Loading forecast…
        </p>
      )}
      {data && <DecisionDetail data={data} stale={loading} onShowOutcome={onShowOutcome} />}
    </section>
  )
}

function DecisionDetail({ data, stale, onShowOutcome }) {
  const { coverage } = data
  const withForecast = data.intervals.filter((i) => i.forecast_mw != null)
  const lowest = withForecast.reduce((a, b) => (b.forecast_mw < a.forecast_mw ? b : a), withForecast[0])
  const highest = withForecast.reduce((a, b) => (b.forecast_mw > a.forecast_mw ? b : a), withForecast[0])
  const mean = withForecast.length
    ? withForecast.reduce((s, i) => s + i.forecast_mw, 0) / withForecast.length
    : null
  const missing = coverage.expected_intervals - coverage.forecast_intervals

  return (
    <div className={stale ? 'stale' : undefined} aria-busy={stale}>
      <h2 id="decision-heading">Delivery day: {longDate(data.delivery_date)}</h2>
      <p className="muted">
        Decision on {longDate(data.decision_date)} at <strong>{data.decision_time} Europe/London</strong> (cutoff{' '}
        <code>{data.decision_cutoff}</code>). The delivery day is the next Europe/London calendar day:{' '}
        {coverage.expected_intervals} hourly intervals.
      </p>

      {coverage.forecast_intervals === 0 ? (
        <Notice tone="empty" title="No forecast available.">
          No forecast for this delivery day had been published by {data.decision_time}. Try a later decision time.
        </Notice>
      ) : (
        missing > 0 && (
          <Notice tone="partial" title="Partial forecast.">
            {missing} of {coverage.expected_intervals} hours had no forecast published by the cutoff. They are left
            blank, not shown as zero.
          </Notice>
        )
      )}

      <div className="stat-row">
        <StatTile label="Average forecast" value={mw(mean)} hint="over hours with a forecast" />
        <StatTile
          label="Lowest hour"
          value={mw(lowest?.forecast_mw)}
          hint={lowest && `at ${londonTime(lowest.target_time)}`}
        />
        <StatTile
          label="Highest hour"
          value={mw(highest?.forecast_mw)}
          hint={highest && `at ${londonTime(highest.target_time)}`}
        />
        <StatTile
          label="Forecast coverage"
          value={percent(coverage.forecast_coverage)}
          hint={`${coverage.forecast_intervals} of ${coverage.expected_intervals} hours`}
          meter={coverage.forecast_coverage}
        />
      </div>

      {withForecast.length > 0 && <ForecastChart intervals={data.intervals} deliveryDate={data.delivery_date} />}

      <PublicationsUsed intervals={data.intervals} />

      <p>
        <button type="button" className="link" onClick={() => onShowOutcome(data.decision_date)}>
          See how this forecast compared with actual generation →
        </button>
      </p>

      <details>
        <summary>Show hourly forecast table</summary>
        <ForecastTable intervals={data.intervals} />
      </details>
    </div>
  )
}

function ForecastChart({ intervals, deliveryDate }) {
  const colours = useChartColors()
  const rows = intervals.map((i) => ({ ...i, label: londonTime(i.target_time) }))
  return (
    <figure className="chart" aria-label={`Hourly wind generation forecast for ${longDate(deliveryDate)}, in MW`}>
      <figcaption>
        Selected wind generation forecast for the delivery day (Europe/London, MW)
        <span className="legend">
          <span className="swatch" style={{ background: colours.forecast }} /> Forecast
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={rows} margin={{ top: 12, right: 16, bottom: 4, left: 8 }}>
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
              const i = payload?.[0]?.payload
              return (
                <ChartTooltip
                  active={active && i}
                  title={i && `${i.label} Europe/London`}
                  rows={
                    i && [
                      ['Forecast', mw(i.forecast_mw), colours.forecast],
                      ['Published', londonDateTime(i.forecast_publish_time)],
                      ['Hours ahead', i.lead_time_hours == null ? '—' : String(i.lead_time_hours)],
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
            connectNulls={false}
            activeDot={{ r: 4, stroke: colours.surface, strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="muted small">Gaps mean no forecast had been published for that hour by the cutoff.</p>
    </figure>
  )
}

function PublicationsUsed({ intervals }) {
  const counts = new Map()
  for (const i of intervals) {
    if (i.forecast_publish_time) {
      counts.set(i.forecast_publish_time, (counts.get(i.forecast_publish_time) ?? 0) + 1)
    }
  }
  if (counts.size === 0) return null
  return (
    <div className="publications">
      <h3>Which forecast publication was used?</h3>
      <p className="muted">
        Each hour uses the <strong>latest forecast published at or before the cutoff</strong> for that hour. Usually
        one publication covers the whole day, but if the newest one does not cover an hour, an older one is used, so
        publication times can differ between hours. Hover the chart to see the publication for each hour.
      </p>
      <ul>
        {[...counts.entries()].map(([published, n]) => (
          <li key={published}>
            Published {londonDateTime(published)} Europe/London: {n} {n === 1 ? 'hour' : 'hours'}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ForecastTable({ intervals }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">Hourly selected forecast with publication time</caption>
        <thead>
          <tr>
            <th scope="col">Hour (Europe/London)</th>
            <th scope="col">Forecast</th>
            <th scope="col">Published</th>
            <th scope="col">Hours ahead</th>
          </tr>
        </thead>
        <tbody>
          {intervals.map((i) => (
            <tr key={i.target_time}>
              <td>{londonTime(i.target_time)}</td>
              <td>{mw(i.forecast_mw)}</td>
              <td>{londonDateTime(i.forecast_publish_time)}</td>
              <td>{i.lead_time_hours ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
