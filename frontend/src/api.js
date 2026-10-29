// URLs for the FastAPI endpoints, and a fetch helper that surfaces API errors.

const withQuery = (path, params) => `${path}?${new URLSearchParams(params)}`

export const metaUrl = () => '/api/meta'

export const forecastUrl = (decisionDate, decisionTime) =>
  withQuery('/api/forecast', { decision_date: decisionDate, decision_time: decisionTime })

export const accuracyUrl = (decisionTime, startDate, endDate) =>
  withQuery('/api/accuracy', { start_date: startDate, end_date: endDate, decision_time: decisionTime })

export async function getJson(url, signal) {
  const response = await fetch(url, { signal })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return body
}
