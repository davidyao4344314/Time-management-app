// Test the real file hook with deterministic fetch/state; no browser or AI charge.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function harness() {
  const values = [], refs = [], calls = []
  let cursor = 0, refCursor = 0, effect, cleanup, responder
  const context = vm.createContext({
    AbortController,
    FormData: class { constructor() { this.entries = [] } append(...entry) { this.entries.push(entry) } },
    useState(initial) { const index = cursor++; if (!(index in values)) values[index] = initial; return [values[index], value => { values[index] = typeof value === 'function' ? value(values[index]) : value }] },
    useRef(initial) { const index = refCursor++; return refs[index] ||= { current: initial } },
    useEffect(callback) { effect ||= callback },
    async fetch(path, options) { calls.push([path, options]); return responder(path, options) },
  })
  const source = fs.readFileSync(new URL('../src/hooks/useImportedFiles.js', import.meta.url), 'utf8')
    .replace(/^import .*\n/, '').replace('export default function', 'function')
  vm.runInContext(source, context)
  const render = () => { cursor = refCursor = 0; return context.useImportedFiles() }
  const response = data => ({ ok: true, json: async () => data })
  responder = () => response({ files: [] })
  return { render, calls, response, setResponder(fn) { responder = fn }, stop() { cleanup?.() },
    async start() { render(); cleanup = effect(); await new Promise(resolve => setImmediate(resolve)); return render() } }
}

test('import uploads bytes once and stores metadata in state without an AI call', async () => {
  const h = harness()
  await h.start()
  const file = { name: 'notes.txt', size: 40 }
  h.setResponder(() => h.response({ file_id: 'file_123', filename: 'notes.txt', file_type: 'txt', chunk_count: 1 }))
  assert.equal(await h.render().upload(file), true)
  assert.equal(h.render().files[0].filename, 'notes.txt')
  assert.match(h.render().message, /No AI request/)
  assert.ok(h.calls.every(([path]) => path === '/api/files'))
  const options = h.calls[1][1]
  assert.equal(options.credentials, 'same-origin')
  assert.equal(options.method, 'POST')
  assert.equal(options.body.entries[0][0], 'file')
  assert.equal(options.body.entries[0][1], file)
})

test('unsupported empty and oversized files do not start an upload', async () => {
  const h = harness()
  await h.start()
  for (const file of [{ name: 'a.zip', size: 10 }, { name: 'a.txt', size: 0 }, { name: 'a.pdf', size: 6 * 1024 * 1024 }]) {
    assert.equal(await h.render().upload(file), false)
    assert.notEqual(h.render().error, '')
  }
  assert.equal(h.calls.length, 1)
})

test('double click starts one upload and a failed request remains retryable', async () => {
  const h = harness()
  await h.start()
  let finish
  h.setResponder(() => new Promise(resolve => { finish = resolve }))
  const file = { name: 'notes.txt', size: 40 }
  const request = h.render().upload(file)
  assert.equal(h.render().uploading, true)
  assert.equal(await h.render().upload(file), false)
  finish({ ok: false, json: async () => ({ detail: 'The document could not be parsed.' }) })
  await request
  assert.equal(h.render().uploading, false)
  assert.match(h.render().error, /could not be parsed/)
  h.setResponder(() => h.response({ file_id: 'id', filename: 'notes.txt' }))
  assert.equal(await h.render().upload(file), true)
})

test('unmount aborts upload and ignores a late response', async () => {
  const h = harness()
  await h.start()
  let finish, signal
  h.setResponder((path, options) => new Promise(resolve => { finish = resolve; signal = options.signal }))
  const upload = h.render().upload({ name: 'notes.txt', size: 40 })
  h.stop()
  assert.equal(signal.aborted, true)
  finish(h.response({ file_id: 'late', filename: 'notes.txt' }))
  assert.equal(await upload, false)
  assert.equal(h.render().files.length, 0)
})
