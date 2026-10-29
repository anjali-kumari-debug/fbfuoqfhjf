// URLs for the FastAPI endpoints, and a fetch helper that surfaces API errors.

const withQuery = (path, params) => `${path}?${new URLSearchParams(params)}`

export const metaUrl = () => '/api/meta'

export const decisionUrl = (date, cutoff) => withQuery('/api/decision', { date, cutoff })

export const accuracyUrl = (cutoff) => withQuery('/api/accuracy', { cutoff })

export async function getJson(url, signal) {
  const response = await fetch(url, { signal })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return body
}
