// Exercise the real hook with deterministic state/fetch; no React test dependency or network.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function harness() {
  const values = [], refs = [], calls = []
  let cursor = 0, refCursor = 0, effect, number = 0, responder
  const context = vm.createContext({
    Map, URL, AbortController,
    window: { location: { href: 'http://localhost/' }, history: { replaceState() {} } },
    crypto: { randomUUID: () => `request-${++number}` },
    useState(initial) {
      const index = cursor++
      if (!(index in values)) values[index] = initial
      return [values[index], value => { values[index] = typeof value === 'function' ? value(values[index]) : value }]
    },
    useRef(initial) { const index = refCursor++; return refs[index] ||= { current: initial } },
    useEffect(callback) { effect ||= callback },
    async fetch(path, options) { calls.push([path, options]); return responder(path, options) },
  })
  const source = fs.readFileSync(new URL('../src/hooks/useConversation.js', import.meta.url), 'utf8')
    .replace(/^import .*\n/, '').replace('export default function', 'function')
  vm.runInContext(source, context)
  const render = () => { cursor = refCursor = 0; return context.useConversation() }
  const response = data => ({ ok: true, json: async () => data })
  responder = path => response(path.endsWith('/messages')
    ? { conversation: { conversation_id: path.split('/')[3] }, messages: [], next_before: null }
    : { conversations: [{ conversation_id: 'chat-1' }] })
  return { render, calls, response, setResponder(fn) { responder = fn },
    async start() { render(); effect(); await new Promise(resolve => setImmediate(resolve)); return render() } }
}

test('ordinary Send after a lost response reuses the existing request ID', async () => {
  const h = harness()
  let state = await h.start()
  state.setDraft('Study tonight')
  h.setResponder(() => { throw new Error('Response lost') })
  await h.render().send()
  assert.equal(h.render().retryAvailable, true)
  await h.render().send()
  const requests = h.calls.filter(([, options]) => options.method === 'POST')
    .map(([, options]) => JSON.parse(options.body).request_id)
  assert.deepEqual(requests, ['request-1', 'request-1'])
})

test('retry belongs to its original chat and list refresh failure does not reopen it', async () => {
  const h = harness()
  let state = await h.start()
  state.setDraft('Study tonight')
  h.setResponder(() => { throw new Error('Response lost') })
  await h.render().send()
  h.setResponder(path => h.response({ conversation: { conversation_id: path.split('/')[3] }, messages: [], next_before: null }))
  await h.render().selectChat('chat-2')
  assert.equal(h.render().retryAvailable, false)
  await h.render().checkLast()
  await h.render().selectChat('chat-1')
  assert.equal(h.render().retryAvailable, true)
  h.setResponder((path, options) => {
    if (options.method === 'POST') return h.response({ status: 'completed', messages: [] })
    throw new Error('List unavailable')
  })
  await h.render().checkLast()
  assert.equal(h.render().retryAvailable, false)
  assert.equal(h.render().draft, '')
})

test('pending response remains resolvable instead of allowing a new request', async () => {
  const h = harness()
  let state = await h.start()
  state.setDraft('Study tonight')
  h.setResponder((path, options) => options.method === 'POST'
    ? h.response({ status: 'pending', messages: [] }) : h.response({ conversations: [] }))
  await h.render().send()
  assert.equal(h.render().retryAvailable, true)
  await h.render().checkLast()
  const ids = h.calls.filter(([, options]) => options.method === 'POST')
    .map(([, options]) => JSON.parse(options.body).request_id)
  assert.deepEqual(ids, ['request-1', 'request-1'])
})
