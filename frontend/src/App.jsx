import { useState } from 'react'
import './App.css'
import { metaUrl } from './api'
import AccuracyView from './components/AccuracyView'
import DecisionView from './components/DecisionView'
import Notice from './components/Notice'
import { useApi } from './useApi'

const VALID_TIME = /^([01]\d|2[0-3]):[0-5]\d$/
const TABS = ['decision', 'accuracy']

export default function App() {
  const { data: meta, error, loading } = useApi(metaUrl())

  return (
    <div className="app">
      <header className="app-header">
        <h1>Wind Forecast Desk</h1>
        <p className="muted">
          Day-ahead wind generation forecasts for Great Britain (metered, transmission-connected wind farms): what was
          known at your decision time, and how accurate it turned out to be.
        </p>
        {meta && <SourceLine meta={meta} />}
      </header>
      {error && (
        <Notice tone="error" title="Could not reach the API.">
          {error.message}
        </Notice>
      )}
      {loading && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {meta && <Dashboard meta={meta} />}
    </div>
  )
}

function SourceLine({ meta }) {
  return (
    <p className="source-line small">
      Source: Elexon BMRS (WINDFOR forecasts, FUELHH wind actuals), snapshot retrieved{' '}
      {meta.data_retrieved_at_utc ? `${meta.data_retrieved_at_utc.replace('T', ' ').replace('Z', '')} UTC` : '—'} ·
      All times Europe/London
    </p>
  )
}

function Dashboard({ meta }) {
  // The tab lives in the URL hash (#decision / #accuracy) so links and refreshes keep the view.
  const [tab, setTabState] = useState(() => (TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'decision'))
  const [date, setDate] = useState(meta.first_decision_date)
  const [decisionTime, setDecisionTime] = useState(meta.default_decision_time)
  const [range, setRange] = useState({ start: meta.first_decision_date, end: meta.last_decision_date })

  const setTab = (next) => {
    history.replaceState(null, '', `#${next}`)
    setTabState(next)
  }
  const openDecision = (day) => {
    setDate(day)
    setTab('decision')
  }
  const showOutcome = (day) => {
    setRange({ start: day, end: day })
    setTab('accuracy')
  }

  return (
    <>
      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="Views">
          <button type="button" role="tab" aria-selected={tab === 'decision'} onClick={() => setTab('decision')}>
            Decision view
          </button>
          <button type="button" role="tab" aria-selected={tab === 'accuracy'} onClick={() => setTab('accuracy')}>
            Accuracy
          </button>
        </div>
        <div className="decision-time">
          <label htmlFor="decision-time">Decision time</label>
          <input
            id="decision-time"
            type="time"
            step={60}
            value={decisionTime}
            aria-describedby="decision-time-note"
            onChange={(e) => VALID_TIME.test(e.target.value) && setDecisionTime(e.target.value)}
          />
          <span className="tz">Europe/London</span>
          <span className="badge" id="decision-time-note" title={meta.decision_time_note}>
            Default {meta.default_decision_time} is an assumption, not a market rule
          </span>
        </div>
      </div>

      <main>
        {tab === 'decision' ? (
          <DecisionView
            meta={meta}
            date={date}
            onDateChange={setDate}
            decisionTime={decisionTime}
            onShowOutcome={showOutcome}
          />
        ) : (
          <AccuracyView
            meta={meta}
            decisionTime={decisionTime}
            range={range}
            onRangeChange={setRange}
            onSelectDay={openDecision}
          />
        )}
      </main>

      <MethodNotes meta={meta} />
    </>
  )
}

function MethodNotes({ meta }) {
  return (
    <footer className="method">
      <h3>How this works</h3>
      <ul>
        <li>
          <strong>Decision and delivery:</strong> a decision on a January 2026 date covers the next Europe/London
          calendar day ({meta.first_decision_date} to {meta.last_decision_date}).
        </li>
        <li>
          <strong>Decision time:</strong> {meta.decision_time_note}
        </li>
        <li>
          <strong>Forecast choice:</strong> {meta.selection_rule}
        </li>
        <li>
          <strong>Matching resolutions:</strong> {meta.alignment_note}
        </li>
        <li>
          <strong>Error:</strong> {meta.error_definition}. MAPE is not used because wind output can be close to zero.
        </li>
        <li>
          <strong>Missing data</strong> is shown as a gap or "—" and counted in coverage. It is never shown as zero.
        </li>
        <li>
          <strong>Scope of the data:</strong> both datasets cover wind farms with operational metering on the
          transmission network, not embedded wind, so these are not total GB wind figures (NESO estimates about 82%).
        </li>
        <li>
          <strong>Not a procurement calculator:</strong> no demand data is included, so this tool cannot say how much
          power to buy. It shows wind forecasts and how wrong they have been, as one input to that decision.
        </li>
        <li>
          <strong>Data:</strong> prepared offline from a snapshot retrieved{' '}
          {meta.data_retrieved_at_utc?.slice(0, 10) ?? '—'}; the dashboard never calls Elexon directly.
        </li>
      </ul>
      {meta.attribution && (
        <p className="small attribution">
          {meta.attribution}{' '}
          {meta.licence_url && (
            <a href={meta.licence_url} target="_blank" rel="noreferrer">
              Licence
            </a>
          )}
        </p>
      )}
    </footer>
  )
}
