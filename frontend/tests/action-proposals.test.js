// Exercise the real hook with deterministic fetch/state and no database writes.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const pending = {
  id: 'proposal-1', display_title: 'Proposed change', display_description: 'Review this exact change.',
  status: 'pending_approval', requires_approval: true, result: null,
}

function harness(dev = true) {
  const values = [], refs = [], calls = []
  let cursor = 0, refCursor = 0, effect, cleanup, responder
  const context = vm.createContext({
    AbortController, encodeURIComponent,
    useState(initial) {
      const index = cursor++
      if (!(index in values)) values[index] = initial
      return [values[index], value => { values[index] = typeof value === 'function' ? value(values[index]) : value }]
    },
    useRef(initial) { const index = refCursor++; return refs[index] ||= { current: initial } },
    useEffect(callback) { effect ||= callback },
    async fetch(path, options) { calls.push([path, options]); return responder(path, options) },
  })
  const source = fs.readFileSync(new URL('../src/hooks/useActionProposals.js', import.meta.url), 'utf8')
    .replace(/^import .*\n/, '').replace('export default function', 'function')
  vm.runInContext(source, context)
  const render = () => { cursor = refCursor = 0; return context.useActionProposals() }
  const response = data => ({ ok: true, json: async () => data })
  responder = () => response({ proposals: [pending], dev_enabled: dev })
  return { render, calls, response, setResponder(fn) { responder = fn }, stop() { cleanup?.() },
    async start() { render(); cleanup = effect(); await new Promise(resolve => setImmediate(resolve)); return render() } }
}

test('loading proposals does not approve or call any other backend path', async () => {
  const h = harness()
  await h.start()
  assert.equal(h.render().proposals[0].display_title, pending.display_title)
  assert.equal(h.render().proposals[0].status, 'pending_approval')
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0][0], '/api/actions/proposals')
  assert.equal(h.calls[0][1].credentials, 'same-origin')
  assert.equal(h.calls[0][1].method, undefined)
})

test('confirm sends only identity and decision and blocks synchronous double clicks', async () => {
  const h = harness()
  await h.start()
  let finish
  h.setResponder(() => new Promise(resolve => { finish = resolve }))
  const state = h.render()
  const request = state.decide(pending.id, 'confirm')
  assert.equal(await state.decide(pending.id, 'confirm'), false)
  assert.equal(h.calls.length, 2)
  assert.equal(h.calls[1][0], '/api/actions/proposals/proposal-1/decision')
  assert.deepEqual(JSON.parse(h.calls[1][1].body), { decision: 'confirm' })
  assert.equal(h.render().busyId, pending.id)
  finish(h.response({ ...pending, status: 'completed', result: { success: true, message: 'Action completed.' } }))
  assert.equal(await request, true)
  assert.equal(h.render().proposals[0].status, 'completed')
  assert.equal(h.render().proposals[0].result.message, 'Action completed.')
  assert.equal(await h.render().decide(pending.id, 'confirm'), false)
  assert.equal(h.calls.length, 2)
})

test('cancel uses the same generic boundary and leaves a rejected presentation', async () => {
  const h = harness()
  await h.start()
  h.setResponder(() => h.response({ ...pending, status: 'rejected' }))
  assert.equal(await h.render().decide(pending.id, 'cancel'), true)
  assert.deepEqual(JSON.parse(h.calls[1][1].body), { decision: 'cancel' })
  assert.equal(h.render().proposals[0].status, 'rejected')
  assert.equal(await h.render().decide(pending.id, 'confirm'), false)
})

test('uncertain network results require a status refresh before any repeat decision', async () => {
  const h = harness()
  await h.start()
  h.setResponder(() => { throw new Error('Network unavailable') })
  assert.equal(await h.render().decide(pending.id, 'confirm'), false)
  assert.equal(h.render().needsRefresh, true)
  assert.match(h.render().error, /Refresh proposals/)
  assert.equal(await h.render().decide(pending.id, 'confirm'), false)
  assert.equal(h.calls.length, 2)
  h.setResponder(() => h.response({ proposals: [{ ...pending, status: 'completed', result: { success: true, message: 'Already completed.' } }], dev_enabled: true }))
  assert.equal(await h.render().refresh(), true)
  assert.equal(h.render().needsRefresh, false)
  assert.equal(h.render().proposals[0].status, 'completed')
  assert.equal(await h.render().decide(pending.id, 'confirm'), false)
})

test('the dev path uses an empty body and cannot choose a tool or arguments', async () => {
  const h = harness()
  await h.start()
  h.setResponder(() => h.response({ ...pending, id: 'proposal-2' }))
  assert.equal(await h.render().createTestProposal(), true)
  assert.equal(h.calls[1][0], '/api/actions/dev/proposals')
  assert.deepEqual(JSON.parse(h.calls[1][1].body), {})
  assert.equal(h.render().proposals.length, 2)
  const disabled = harness(false)
  await disabled.start()
  assert.equal(await disabled.render().createTestProposal(), false)
  assert.equal(disabled.calls.length, 1)
})

test('unknown IDs and invalid decisions do not send a request', async () => {
  const h = harness()
  await h.start()
  assert.equal(await h.render().decide('other', 'confirm'), false)
  assert.equal(await h.render().decide(pending.id, 'approve'), false)
  assert.equal(h.calls.length, 1)
})

test('unmount aborts the browser request and ignores late results without retrying', async () => {
  const h = harness()
  await h.start()
  let finish, signal
  h.setResponder((path, options) => new Promise(resolve => { finish = resolve; signal = options.signal }))
  const request = h.render().decide(pending.id, 'confirm')
  h.stop()
  assert.equal(signal.aborted, true)
  finish(h.response({ ...pending, status: 'completed' }))
  assert.equal(await request, false)
  assert.equal(h.render().proposals[0].status, 'pending_approval')
  assert.equal(h.calls.length, 2)
})
