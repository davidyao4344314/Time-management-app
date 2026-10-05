// Exercise the real hook with deterministic state/fetch; no React test dependency or network.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function harness() {
  const values = [], refs = [], calls = []
  let cursor = 0, refCursor = 0, effect, cleanup, number = 0, responder
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
    stop() { cleanup?.() },
    async start() { render(); cleanup = effect(); await new Promise(resolve => setImmediate(resolve)); return render() } }
}

async function paginatedChat(h, id = 'chat-1') {
  h.setResponder(() => h.response({
    conversation: { conversation_id: id },
    messages: [{ message_id: 'new', content: 'Newest saved reply', sequence_number: 3 }],
    next_before: 3,
  }))
  await h.render().selectChat(id)
}

test('earlier-message loading permits one request at a time and keeps current overlapping messages', async () => {
  const h = harness()
  await h.start()
  await paginatedChat(h)
  let finish
  h.setResponder(() => new Promise(resolve => { finish = resolve }))
  const state = h.render()
  const loading = state.loadOlder()
  await state.loadOlder() // A second click before React has re-rendered.
  assert.equal(h.render().loadingOlder, true)
  assert.equal(h.calls.filter(([path]) => path.includes('?before=')).length, 1)
  finish(h.response({ messages: [
    { message_id: 'old', content: 'Older reply', sequence_number: 1 },
    { message_id: 'old', content: 'Duplicate', sequence_number: 1 },
    { message_id: 'new', content: 'Stale copy', sequence_number: 3 },
  ], next_before: 1 }))
  await loading
  const updated = h.render()
  assert.equal(updated.loadingOlder, false)
  assert.equal(updated.nextBefore, 1)
  assert.equal(updated.messages.length, 2)
  assert.equal(updated.messages[0].message_id, 'old')
  assert.equal(updated.messages[1].content, 'Newest saved reply')
})

test('a failed earlier-message request keeps existing messages and can be retried', async () => {
  const h = harness()
  await h.start()
  await paginatedChat(h)
  h.setResponder(() => { throw new Error('Network unavailable') })
  await h.render().loadOlder()
  assert.equal(h.render().loadingOlder, false)
  assert.equal(h.render().messages.length, 1)
  assert.equal(h.render().nextBefore, 3)
  assert.equal(h.render().error, 'Network unavailable')
  h.setResponder(() => h.response({ messages: [], next_before: null }))
  await h.render().loadOlder()
  assert.equal(h.render().nextBefore, null)
  assert.equal(h.render().error, '')
})

test('switching chats cancels pagination and clears the old page cursor immediately', async () => {
  const h = harness()
  await h.start()
  await paginatedChat(h)
  let finishOlder, finishChat, signal
  h.setResponder((path, options) => new Promise(resolve => {
    if (path.includes('?before=')) { finishOlder = resolve; signal = options.signal }
    else finishChat = resolve
  }))
  const earlier = h.render().loadOlder()
  const changing = h.render().selectChat('chat-2')
  assert.equal(signal.aborted, true)
  assert.equal(h.render().loadingOlder, false)
  assert.equal(h.render().nextBefore, null)
  finishChat(h.response({ conversation: { conversation_id: 'chat-2' }, messages: [], next_before: null }))
  await changing
  finishOlder(h.response({ messages: [{ message_id: 'wrong-chat' }], next_before: 1 }))
  await earlier
  assert.equal(h.render().chat.conversation_id, 'chat-2')
  assert.equal(h.render().messages.length, 0)
  assert.equal(h.render().nextBefore, null)
})

test('returning to the same chat cannot revive an aborted pagination response', async () => {
  const h = harness()
  await h.start()
  await paginatedChat(h)
  let finish
  h.setResponder(() => new Promise(resolve => { finish = resolve }))
  const earlier = h.render().loadOlder()
  await paginatedChat(h, 'chat-2')
  await paginatedChat(h, 'chat-1')
  finish(h.response({ messages: [{ message_id: 'stale' }], next_before: 1 }))
  await earlier
  assert.equal(h.render().messages.length, 1)
  assert.equal(h.render().messages[0].message_id, 'new')
  assert.equal(h.render().nextBefore, 3)
})

test('leaving the page aborts the earlier-message request without changing state', async () => {
  const h = harness()
  await h.start()
  await paginatedChat(h)
  let finish, signal
  h.setResponder((path, options) => new Promise(resolve => { finish = resolve; signal = options.signal }))
  const earlier = h.render().loadOlder()
  h.stop()
  assert.equal(signal.aborted, true)
  finish(h.response({ messages: [{ message_id: 'stale' }], next_before: null }))
  await earlier
  assert.equal(h.render().messages.length, 1)
  assert.equal(h.render().nextBefore, 3)
})

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
