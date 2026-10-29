// Chart colours for light and dark mode. Pairs were checked for colour-blind
// separation and contrast (forecast/actual, and under/over-forecast).
import { useSyncExternalStore } from 'react'

const LIGHT = {
  forecast: '#2a78d6',
  actual: '#eb6834',
  under: '#2a78d6', // forecast below actual (negative error)
  over: '#e34948', // forecast above actual (positive error)
  grid: '#e1e0d9',
  axis: '#c3c2b7',
  muted: '#898781',
  surface: '#fcfcfb',
}

const DARK = {
  forecast: '#3987e5',
  actual: '#d95926',
  under: '#3987e5',
  over: '#e66767',
  grid: '#2c2c2a',
  axis: '#383835',
  muted: '#898781',
  surface: '#1a1a19',
}

const query = window.matchMedia('(prefers-color-scheme: dark)')

const subscribe = (callback) => {
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

export function useChartColors() {
  const dark = useSyncExternalStore(subscribe, () => query.matches)
  return dark ? DARK : LIGHT
}
