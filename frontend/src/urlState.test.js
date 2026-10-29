// Run from frontend/: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildSearch, defaultState, parseState } from './urlState.js'

const meta = { first_decision_date: '2026-01-01', last_decision_date: '2026-01-31', default_decision_time: '10:00' }

test('a full link restores every setting', () => {
  const state = { view: 'accuracy', date: '2026-01-15', time: '16:00', start: '2026-01-10', end: '2026-01-20' }
  assert.deepEqual(parseState(buildSearch(state), '', meta), state)
})

test('no link gives the defaults', () => {
  assert.deepEqual(parseState('', '', meta), defaultState(meta))
})

test('invalid or out-of-range values fall back to defaults instead of breaking the page', () => {
  const s = parseState('?view=admin&date=2026-02-05&time=25:00&start=yesterday&end=2026-01-32', '', meta)
  assert.deepEqual(s, defaultState(meta))
})

test('old #accuracy links still open the accuracy view', () => {
  assert.equal(parseState('', '#accuracy', meta).view, 'accuracy')
  assert.equal(parseState('?view=decision', '#accuracy', meta).view, 'decision') // query wins
})
