// A labelled number. `meter` (0..1) adds a small coverage bar with its own text alternative.
export default function StatTile({ label, value, hint, meter }) {
  return (
    <div className="stat-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {meter != null && (
        <div
          className="meter"
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(meter * 100)}
        >
          <span style={{ width: `${Math.max(0, Math.min(1, meter)) * 100}%` }} />
        </div>
      )}
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}
