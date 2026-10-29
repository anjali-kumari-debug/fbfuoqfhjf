import { useState } from 'react'
import './App.css'
import { metaUrl } from './api'
import AccuracyView from './components/AccuracyView'
import DecisionView from './components/DecisionView'
import { useApi } from './useApi'

const VALID_CUTOFF = /^([01]\d|2[0-3]):[0-5]\d$/

export default function App() {
  const { data: meta, error } = useApi(metaUrl())

  return (
    <div className="app">
      <header className="app-header">
        <h1>Wind Forecast Desk</h1>
        <p className="muted">
          Great Britain national wind generation: the day-ahead forecast available at your decision time, and how
          accurate those forecasts turned out to be.
        </p>
      </header>
      {error && <p className="error">Could not reach the API: {error.message}</p>}
      {meta && <Dashboard meta={meta} />}
    </div>
  )
}

const TABS = ['decision', 'accuracy']

function Dashboard({ meta }) {
  // The tab lives in the URL hash (#decision / #accuracy) so links and refreshes keep the view.
  const [tab, setTabState] = useState(() => (TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'decision'))
  const [date, setDate] = useState(meta.first_decision_date)
  const [cutoff, setCutoff] = useState(meta.default_cutoff)

  const setTab = (next) => {
    history.replaceState(null, '', `#${next}`)
    setTabState(next)
  }

  const openDay = (day) => {
    setDate(day)
    setTab('decision')
  }

  return (
    <>
      <div className="toolbar">
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === 'decision'} onClick={() => setTab('decision')}>
            Decision view
          </button>
          <button type="button" role="tab" aria-selected={tab === 'accuracy'} onClick={() => setTab('accuracy')}>
            Accuracy over January
          </button>
        </div>
        <label className="cutoff">
          Decision cutoff (London time)
          <input
            type="time"
            step={60}
            value={cutoff}
            onChange={(e) => VALID_CUTOFF.test(e.target.value) && setCutoff(e.target.value)}
          />
          <span className="badge" title={meta.cutoff_note}>
            Demo assumption, not a market rule
          </span>
        </label>
      </div>

      <main>
        {tab === 'decision' ? (
          <DecisionView meta={meta} date={date} onDateChange={setDate} cutoff={cutoff} />
        ) : (
          <AccuracyView cutoff={cutoff} onSelectDay={openDay} />
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
          <strong>Decision and delivery:</strong> a decision is made on a January 2026 date and covers the next London
          calendar day ({meta.first_decision_date} to {meta.last_decision_date} decisions).
        </li>
        <li>
          <strong>Forecast choice:</strong> {meta.selection_rule}
        </li>
        <li>
          <strong>Matching resolutions:</strong> {meta.alignment_note}
        </li>
        <li>
          <strong>Error:</strong> {meta.error_convention}. MAPE is not used because wind output can be close to zero.
        </li>
        <li>
          <strong>Missing data</strong> is shown as a gap or "—" and counted in coverage. It is never filled in.
        </li>
        <li>
          <strong>Data:</strong> Elexon BMRS FUELHH (WIND) actuals and WINDFOR forecasts, from a snapshot taken{' '}
          {meta.snapshot_generated_at_utc?.slice(0, 10)}. All times shown in {meta.timezone} time.
        </li>
        <li>
          This tool reports forecasts and their errors. It does not recommend how much power to buy.
        </li>
      </ul>
    </footer>
  )
}
