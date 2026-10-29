import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { accuracyUrl } from '../api'
import { longDate, mw, percent, shortDate, signedMw } from '../format'
import { useChartColors } from '../theme'
import { useApi } from '../useApi'
import ChartTooltip from './ChartTooltip'
import StatTile from './StatTile'

const kiloTick = (v) => (v === 0 ? '0' : `${v / 1000}k`)

export default function AccuracyView({ cutoff, onSelectDay }) {
  const { data, error, loading } = useApi(accuracyUrl(cutoff))

  if (error) return <p className="error">Could not load accuracy: {error.message}</p>
  if (!data) return <p className="muted">Loading…</p>

  const overall = data.pooled
  const days = data.days.map((d) => ({ ...d, label: shortDate(d.delivery_date) }))

  return (
    <section className={loading ? 'stale' : undefined}>
      <h2>Forecast accuracy for every January decision at {data.decision_time}</h2>
      <p className="muted">
        Each decision uses the latest forecast available at its cutoff, scored against what was actually generated
        the next day. Change the cutoff above to see how forecast age affects accuracy.
      </p>

      <div className="stat-row">
        <StatTile label="MAE" value={mw(overall.mae_mw)} hint="typical size of the miss" />
        <StatTile label="Bias (mean error)" value={signedMw(overall.bias_mw)} hint="+ means over-forecast" />
        <StatTile label="RMSE" value={mw(overall.rmse_mw)} hint="penalises large misses" />
        <StatTile
          label="Middle 80% of errors"
          value={`${signedMw(overall.p10_mw)} to ${signedMw(overall.p90_mw)}`}
          hint="10th to 90th percentile"
        />
        <StatTile
          label="Coverage"
          value={percent(overall.matched_coverage)}
          hint={`${overall.matched_intervals} of ${overall.expected_intervals} hours scored`}
        />
      </div>

      <DailyMaeChart days={days} onSelectDay={onSelectDay} />
      <DailyBiasChart days={days} onSelectDay={onSelectDay} />
      <ErrorHistogram bins={data.error_histogram} binMw={data.histogram_bin_mw} />

      <details>
        <summary>Show daily table</summary>
        <DailyTable days={days} onSelectDay={onSelectDay} />
      </details>
    </section>
  )
}

function axisProps(colours) {
  return {
    tickLine: false,
    stroke: colours.axis,
    tick: { fill: colours.muted, fontSize: 12 },
  }
}

function dayTooltip() {
  return function DayTooltip({ active, payload }) {
    const d = payload?.[0]?.payload
    return (
      <ChartTooltip
        active={active && d}
        title={d && `Delivery ${longDate(d.delivery_date)}`}
        rows={
          d && [
            ['MAE', mw(d.mae_mw)],
            ['Bias', signedMw(d.bias_mw)],
            ['Scored hours', `${d.matched_intervals} of ${d.expected_intervals}`],
            ['', 'Click to open this day'],
          ]
        }
      />
    )
  }
}

function DailyMaeChart({ days, onSelectDay }) {
  const colours = useChartColors()
  return (
    <figure className="chart">
      <figcaption>Mean absolute error by delivery day (MW)</figcaption>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={days} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={colours.grid} vertical={false} />
          <XAxis dataKey="label" interval={2} {...axisProps(colours)} />
          <YAxis width={48} axisLine={false} tickFormatter={kiloTick} {...axisProps(colours)} />
          <Tooltip cursor={{ fill: colours.grid, opacity: 0.5 }} content={dayTooltip()} />
          <Bar
            dataKey="mae_mw"
            fill={colours.forecast}
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
            cursor="pointer"
            onClick={(entry) => onSelectDay(entry.payload?.decision_date ?? entry.decision_date)}
          />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}

function DailyBiasChart({ days, onSelectDay }) {
  const colours = useChartColors()
  return (
    <figure className="chart">
      <figcaption>
        Bias (mean error) by delivery day (MW)
        <span className="legend">
          <span className="swatch" style={{ background: colours.over }} /> Over-forecast
          <span className="swatch" style={{ background: colours.under }} /> Under-forecast
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={days} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={colours.grid} vertical={false} />
          <XAxis dataKey="label" interval={2} {...axisProps(colours)} />
          <YAxis width={48} axisLine={false} tickFormatter={kiloTick} {...axisProps(colours)} />
          <ReferenceLine y={0} stroke={colours.axis} />
          <Tooltip cursor={{ fill: colours.grid, opacity: 0.5 }} content={dayTooltip()} />
          <Bar
            dataKey="bias_mw"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
            cursor="pointer"
            onClick={(entry) => onSelectDay(entry.payload?.decision_date ?? entry.decision_date)}
          >
            {days.map((d) => (
              <Cell key={d.decision_date} fill={d.bias_mw >= 0 ? colours.over : colours.under} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}

function ErrorHistogram({ bins, binMw }) {
  const colours = useChartColors()
  const rows = bins.map((b) => ({ ...b, label: kiloTick(b.from_mw) }))
  return (
    <figure className="chart">
      <figcaption>
        Distribution of hourly errors, all January decisions ({binMw} MW bins, number of hours)
        <span className="legend">
          <span className="swatch" style={{ background: colours.over }} /> Over-forecast
          <span className="swatch" style={{ background: colours.under }} /> Under-forecast
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 8 }} barCategoryGap={2}>
          <CartesianGrid stroke={colours.grid} vertical={false} />
          <XAxis dataKey="label" interval={1} {...axisProps(colours)} />
          <YAxis width={48} axisLine={false} allowDecimals={false} {...axisProps(colours)} />
          <Tooltip
            cursor={{ fill: colours.grid, opacity: 0.5 }}
            content={({ active, payload }) => {
              const b = payload?.[0]?.payload
              return (
                <ChartTooltip
                  active={active && b}
                  title={b && `Error ${signedMw(b.from_mw)} to ${signedMw(b.to_mw)}`}
                  rows={b && [['Hours', String(b.count)]]}
                />
              )
            }}
          />
          <Bar dataKey="count" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {rows.map((b) => (
              <Cell key={b.from_mw} fill={b.from_mw >= 0 ? colours.over : colours.under} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="muted small">Labels show the lower edge of each bin. Errors at or above 0 are over-forecasts.</p>
    </figure>
  )
}

function DailyTable({ days, onSelectDay }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Decision date</th>
          <th>Delivery date</th>
          <th>MAE</th>
          <th>Bias</th>
          <th>RMSE</th>
          <th>Scored hours</th>
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
            <td>{signedMw(d.bias_mw)}</td>
            <td>{mw(d.rmse_mw)}</td>
            <td>
              {d.matched_intervals} of {d.expected_intervals}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
