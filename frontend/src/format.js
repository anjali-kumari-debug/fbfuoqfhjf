// Display helpers. The API sends UTC timestamps; we always show Europe/London time.

const LONDON = 'Europe/London'

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  hour: '2-digit',
  minute: '2-digit',
})

const dateTimeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

const numberFormat = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 })

export const londonTime = (iso) => (iso ? timeFormat.format(new Date(iso)) : '—')

export const londonDateTime = (iso) => (iso ? dateTimeFormat.format(new Date(iso)) : '—')

// Calendar dates ('2026-01-16') are already London days; format without shifting.
export const shortDate = (isoDate) =>
  new Date(`${isoDate}T12:00:00Z`).toLocaleDateString('en-GB', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'short',
  })

export const longDate = (isoDate) =>
  new Date(`${isoDate}T12:00:00Z`).toLocaleDateString('en-GB', {
    timeZone: 'UTC',
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

export const mw = (value) => (value == null ? '—' : `${numberFormat.format(value)} MW`)

export const signedMw = (value) =>
  value == null ? '—' : `${value > 0 ? '+' : ''}${numberFormat.format(value)} MW`

export const percent = (ratio) => (ratio == null ? '—' : `${Math.round(ratio * 1000) / 10}%`)

export const addDays = (isoDate, days) => {
  const d = new Date(`${isoDate}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const dayFormat = new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, day: 'numeric', month: 'short' })

// London calendar day of a UTC timestamp, e.g. '11 Jan'.
export const londonDay = (iso) => (iso ? dayFormat.format(new Date(iso)) : '—')
