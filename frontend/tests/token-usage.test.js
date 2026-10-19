import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithOxc } from 'vite'

async function load(path, globals = {}) {
  const source = fs.readFileSync(new URL(`../src/components/${path}`, import.meta.url), 'utf8')
  const transformed = await transformWithOxc(source, path)
  const context = vm.createContext({ _jsx: jsx, _jsxs: jsxs, _Fragment: Fragment, ...globals })
  vm.runInContext(transformed.code.replace(/^import .*$/gm, '').replace('export default function', 'function')
    .replace(/^export default \w+;?$/gm, ''), context)
  return context
}

const Panel = (await load('TokenUsagePanel.jsx')).TokenUsagePanel
const base = { stage: 'stage_1', call: 0, label: 'Stage 1 — Local keyword router', model: null,
  status: 'local', measurement: 'local', input_tokens: 0, output_tokens: 0, total_tokens: 0,
  cached_input_tokens: 0, reasoning_output_tokens: 0, context_estimates: {} }
const usage = { totals: { measurement: 'reported', model_calls: 1, input_tokens: 1200, output_tokens: 200, total_tokens: 1400 },
  stages: [base, { ...base, stage: 'main_agent', call: 1, label: 'Main agent', model: 'test-model',
    status: 'completed', measurement: 'reported', input_tokens: 1200, output_tokens: 200, total_tokens: 1400,
    cached_input_tokens: 100, reasoning_output_tokens: 50, context_estimates: { activities: 80, instructions: 200 } }],
  note: 'Cached input and reasoning output are included, not added twice.', estimate_method: 'Rough bytes / 4 estimate.' }

test('API counts and local zero show separately from estimated context components', () => {
  const html = renderToStaticMarkup(jsx(Panel, { usage }))
  assert.match(html, /API reported/)
  assert.match(html, /1,400/)
  assert.match(html, /Stage 1 — Local keyword router/)
  assert.match(html, /Cached input \(included\)/)
  assert.match(html, /Reasoning output \(included\)/)
  assert.match(html, /Estimated input breakdown/)
  assert.match(html, /≈80/)
  assert.match(html, /not a dollar charge/)
})

test('mixed and unavailable values never pretend to be exact or zero', () => {
  const modified = { ...usage, totals: { ...usage.totals, measurement: 'mixed', output_tokens: null, total_tokens: null } }
  const html = renderToStaticMarkup(jsx(Panel, { usage: modified }))
  assert.match(html, /Reported \+ estimates/)
  assert.match(html, /≈1,200/)
  assert.match(html, /Unknown/)
})

test('older messages do not get invented historical counts', () => {
  const html = renderToStaticMarkup(jsx(Panel, {}))
  assert.match(html, /unavailable for this older response/)
  assert.doesNotMatch(html, /Total input/)
})

test('the existing inspector renders the token panel without any network request', async () => {
  const Inspector = (await load('AgentContextInspector.jsx', { TokenUsagePanel: Panel })).AgentContextInspector
  const context = { authority_note: 'Current observations take priority.', routing: { label: 'Stage 1' },
    context_sources: [], memory_message: 'Not requested.', memory_lookups: [], retrieved_memory: [], token_usage: usage }
  const html = renderToStaticMarkup(jsx(Inspector, { context }))
  assert.match(html, /How the agent used context/)
  assert.match(html, /Token Usage/)
  assert.match(html, /1,400/)
})

test('model labels stay escaped and cannot inject HTML', () => {
  const modified = { ...usage, stages: [{ ...usage.stages[1], model: '<script>bad()</script>' }] }
  const html = renderToStaticMarkup(jsx(Panel, { usage: modified }))
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
})
