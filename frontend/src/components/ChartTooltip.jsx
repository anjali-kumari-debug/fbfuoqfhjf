// Shared tooltip box for Recharts. `rows` is a list of [label, value, colour?].
export default function ChartTooltip({ active, title, rows }) {
  if (!active || !rows) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-title">{title}</div>
      {rows.map(([label, value, colour]) => (
        <div className="chart-tooltip-row" key={label}>
          <span>
            {colour && <span className="swatch" style={{ background: colour }} />}
            {label}
          </span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  )
}
