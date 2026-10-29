// Run from frontend/: npm test   (uses Node's built-in test runner, no extra packages)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addDays, londonDateTime, londonTime, mw, percent, shortDate, signedMw } from './format.js'

test('UTC timestamps are shown in London time', () => {
  assert.equal(londonTime('2026-01-16T00:00:00Z'), '00:00') // winter: London = UTC
  assert.equal(londonTime('2026-06-01T09:00:00Z'), '10:00') // summer: London = UTC+1
  assert.equal(londonDateTime('2026-01-15T09:30:00Z'), '15 Jan, 09:30')
})

test('missing values are shown as a dash, never as zero', () => {
  for (const format of [mw, signedMw, percent, londonTime, londonDateTime]) {
    assert.equal(format(null), '—')
    assert.equal(format(undefined), '—')
  }
  assert.equal(mw(0), '0 MW') // a real zero is still shown as zero
})

test('MW values are rounded with thousands separators', () => {
  assert.equal(mw(18365.4), '18,365 MW')
})

test('signed errors show + for over-forecast', () => {
  assert.equal(signedMw(1730), '+1,730 MW')
  assert.equal(signedMw(-489), '-489 MW')
  assert.equal(signedMw(0), '0 MW')
})

test('coverage ratios are shown as percentages', () => {
  assert.equal(percent(1), '100%')
  assert.equal(percent(22 / 24), '91.7%')
})

test('calendar dates move across month ends without timezone shifts', () => {
  assert.equal(addDays('2026-01-31', 1), '2026-02-01')
  assert.equal(addDays('2026-01-01', -1), '2025-12-31')
  assert.equal(shortDate('2026-02-01'), '1 Feb')
})
