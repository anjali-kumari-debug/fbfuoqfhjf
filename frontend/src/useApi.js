import { useEffect, useState } from 'react'
import { getJson } from './api'

// Fetches `url` and refetches whenever it changes. The previous request is
// cancelled, so a slow old response can never overwrite a newer one.
// While a new URL loads, the previous data stays available (loading = true).
export function useApi(url) {
  const [result, setResult] = useState({ url: null, data: null, error: null })

  useEffect(() => {
    const controller = new AbortController()
    getJson(url, controller.signal)
      .then((data) => setResult({ url, data, error: null }))
      .catch((error) => {
        if (!controller.signal.aborted) setResult({ url, data: null, error })
      })
    return () => controller.abort()
  }, [url])

  const loading = result.url !== url
  return { data: result.data, error: loading ? null : result.error, loading }
}
