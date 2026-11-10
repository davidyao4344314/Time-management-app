import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { useState } from 'react'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithOxc } from 'vite'

const day = '2026-11-11'
const session = { activity_id: 7, name: 'Revision', subject: 'COMPSCI 130', category: 'Study',
  start_time: '09:00', end_time: '10:00', completion: null }
const listing = { date: day, today: day, sessions: [session] }
const tick = () => new Promise(resolve => setImmediate(resolve))

function harness() {
  const values = [], refs = [], effects = [], calls = []
  let stateCursor, refCursor, effectCursor, responder
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })
  responder = () => response(listing)
  const context = vm.createContext({
    AbortController,
    useState(initial) {
      const index = stateCursor++
      if (!(index in values)) values[index] = initial
      return [values[index], value => { values[index] = typeof value === 'function' ? value(values[index]) : value }]
    },
    useRef(initial) { const index = refCursor++; return refs[index] ||= { current: initial } },
    useEffect(callback, dependencies) {
      const index = effectCursor++, previous = effects[index]
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))) {
        effects[index] = { callback, dependencies, cleanup: previous?.cleanup, pending: true }
      }
    },
    async fetch(path, options) { calls.push([path, options]); return responder(path, options) },
  })
  const source = fs.readFileSync(new URL('../src/hooks/useStudySessions.js', import.meta.url), 'utf8')
    .replace(/^import .*\n/, '').replace('export default function', 'function')
  vm.runInContext(source, context)
  const render = () => {
    stateCursor = refCursor = effectCursor = 0
    const result = context.useStudySessions()
    for (const effect of effects) if (effect.pending) {
      effect.cleanup?.(); effect.pending = false; effect.cleanup = effect.callback()
    }
    return result
  }
  return { render, calls, response, setResponder(fn) { responder = fn },
    stop() { effects.forEach(effect => effect.cleanup?.()) },
    async flush() { render(); await tick(); return render() } }
}

test('load uses the backend date and saving updates one dated occurrence', async () => {
  const h = harness()
  assert.equal((await h.flush()).date, day)
  const completion = { status: 'partly_done', actual_minutes: 25, updated_at: 'now' }
  h.setResponder(() => h.response(completion))
  await h.render().save(7, { status: 'partly_done', actual_minutes: 25 })
  assert.equal(h.calls[1][0], `/api/study-sessions/7/${day}`)
  assert.equal(h.calls[1][1].method, 'PUT')
  assert.deepEqual(JSON.parse(h.calls[1][1].body), { status: 'partly_done', actual_minutes: 25 })
  assert.equal(h.render().data.sessions[0].completion.actual_minutes, 25)
})

test('double save sends once and date switching is blocked during the write', async () => {
  const h = harness()
  await h.flush()
  let finish
  h.setResponder(() => new Promise(resolve => { finish = resolve }))
  const saving = h.render().save(7, { status: 'missed', actual_minutes: 0 })
  await h.render().save(7, { status: 'done', actual_minutes: 60 })
  h.render().selectDate('2026-11-10')
  assert.equal(h.render().date, day)
  assert.equal(h.calls.length, 2)
  finish(h.response({ status: 'missed', actual_minutes: 0 }))
  await saving
  assert.equal(h.render().savingId, null)
})

test('failed save retains the loaded record and permits an explicit retry', async () => {
  const h = harness()
  await h.flush()
  h.setResponder(() => h.response({ detail: 'Storage unavailable.' }, 500))
  await h.render().save(7, { status: 'done', actual_minutes: 60 })
  assert.match(h.render().error, /Storage unavailable/)
  assert.equal(h.render().data.sessions[0].completion, null)
  h.setResponder(() => h.response({ status: 'done', actual_minutes: 60 }))
  await h.render().save(7, { status: 'done', actual_minutes: 60 })
  assert.equal(h.render().error, '')
  assert.equal(h.render().data.sessions[0].completion.status, 'done')
})

test('clear uses DELETE and reloads the saved occurrence list', async () => {
  const h = harness()
  await h.flush()
  h.setResponder((path, options) => options.method === 'DELETE' ? h.response(null, 204) : h.response(listing))
  await h.render().save(7, null)
  await h.flush()
  assert.equal(h.calls[1][1].method, 'DELETE')
  assert.equal(h.calls.length, 3)
  assert.equal(h.render().data.sessions[0].completion, null)
})

test('switching dates aborts old loads and never displays their late results', async () => {
  const h = harness()
  await h.flush()
  let oldFinish, oldSignal
  h.setResponder((path, options) => new Promise(resolve => {
    if (path.endsWith('2026-11-10')) { oldFinish = resolve; oldSignal = options.signal }
    else resolve(h.response({ ...listing, date: '2026-11-09', sessions: [] }))
  }))
  h.render().selectDate('2026-11-10')
  h.render()
  h.render().selectDate('2026-11-09')
  await h.flush()
  assert.equal(oldSignal.aborted, true)
  oldFinish(h.response({ ...listing, date: '2026-11-10' }))
  await tick()
  assert.equal(h.render().data.date, '2026-11-09')
  assert.equal(h.render().data.sessions.length, 0)
})

test('unmount aborts a write and ignores its late response', async () => {
  const h = harness()
  await h.flush()
  let finish, signal
  h.setResponder((path, options) => new Promise(resolve => { finish = resolve; signal = options.signal }))
  const saving = h.render().save(7, { status: 'done', actual_minutes: 30 })
  h.stop()
  assert.equal(signal.aborted, true)
  finish(h.response({ status: 'done', actual_minutes: 30 }))
  await saving
  assert.equal(h.render().data.sessions[0].completion, null)
})

const source = fs.readFileSync(new URL('../src/components/StudySessionLog.jsx', import.meta.url), 'utf8')
const transformed = await transformWithOxc(source, 'StudySessionLog.jsx')
const context = vm.createContext({ _jsx: jsx, _jsxs: jsxs, _Fragment: Fragment, useState,
  useStudySessions: () => ({ data: listing, date: day, today: day, loading: false, error: '', savingId: null }),
})
vm.runInContext(transformed.code.replace(/^import .*$/gm, '').replace('export default function', 'function'), context)

test('session log renders accessible outcomes, date selection, minutes and saved totals', () => {
  const html = renderToStaticMarkup(jsx(context.StudySessionLog, {}))
  assert.match(html, /Study session log/)
  assert.match(html, /type="date"[^>]*max="2026-11-11"/)
  assert.match(html, /Done<\/option>/)
  assert.match(html, /Partly done/)
  assert.match(html, /Missed/)
  assert.match(html, /Actual minutes/)
  assert.match(html, /Not recorded/)
  assert.match(html, /0 of 1 sessions recorded/)
  const missed = renderToStaticMarkup(jsx(context.SessionForm, {
    session: { ...session, completion: { status: 'missed', actual_minutes: 0 } }, date: day,
  }))
  assert.match(missed, /Missed · 0 min logged/)
  assert.match(missed, /Clear record/)
  assert.match(missed, /type="number"[^>]*disabled=""/)
})
