// Shareable links: the current view lives in the URL query string, e.g.
//   /?view=decision&date=2026-01-15&time=10:00&start=2026-01-01&end=2026-01-31
// Invalid or out-of-range values fall back to the defaults, so a bad link never breaks the page.

const VIEWS = ['decision', 'accuracy']
const DATE = /^\d{4}-\d{2}-\d{2}$/
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/

const inRange = (value, meta) =>
  DATE.test(value ?? '') && value >= meta.first_decision_date && value <= meta.last_decision_date

export function defaultState(meta) {
  return {
    view: 'decision',
    date: meta.first_decision_date,
    time: meta.default_decision_time,
    start: meta.first_decision_date,
    end: meta.last_decision_date,
  }
}

// search: e.g. '?view=accuracy&time=16:00'; hash: legacy '#accuracy' links still work.
export function parseState(search, hash, meta) {
  const q = new URLSearchParams(search)
  const d = defaultState(meta)
  const legacyView = hash?.replace('#', '')
  const view = q.get('view') ?? legacyView
  return {
    view: VIEWS.includes(view) ? view : d.view,
    date: inRange(q.get('date'), meta) ? q.get('date') : d.date,
    time: TIME.test(q.get('time') ?? '') ? q.get('time') : d.time,
    start: inRange(q.get('start'), meta) ? q.get('start') : d.start,
    end: inRange(q.get('end'), meta) ? q.get('end') : d.end,
  }
}

export function buildSearch(state) {
  const { view, date, time, start, end } = state
  return `?${new URLSearchParams({ view, date, time, start, end })}`
}
