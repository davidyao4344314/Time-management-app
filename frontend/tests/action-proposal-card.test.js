// Render the actual JSX using the existing Vite transformer, without a new test library.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { jsx, jsxs } from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithOxc } from 'vite'

const source = fs.readFileSync(new URL('../src/components/ActionProposalCard.jsx', import.meta.url), 'utf8')
const transformed = await transformWithOxc(source, 'ActionProposalCard.jsx')
const context = vm.createContext({ _jsx: jsx, _jsxs: jsxs })
vm.runInContext(transformed.code.replace(/^import .*$/gm, '').replace('export default function', 'function'), context)
const Card = context.ActionProposalCard
const proposal = {
  id: 'backend-id', display_title: 'A generic proposed change', display_description: 'Exact details <not HTML>',
  status: 'pending_approval', requires_approval: true, result: null,
  arguments: { secret_internal: 'must-not-be-rendered' }, tool_name: 'future_tool',
}

test('the generic card renders display fields safely and sends only ID plus decision', () => {
  const calls = []
  const props = { proposal, onDecision: (...args) => calls.push(args), disabled: false, busy: false }
  const html = renderToStaticMarkup(jsx(Card, props))
  assert.match(html, /A generic proposed change/)
  assert.match(html, /Exact details &lt;not HTML&gt;/)
  assert.match(html, />Confirm</)
  assert.match(html, />Cancel</)
  assert.doesNotMatch(html, /future_tool|must-not-be-rendered/)
  const controls = Card(props).props.children.find(child => child?.type === 'div')
  controls.props.children[0].props.onClick()
  controls.props.children[1].props.onClick()
  assert.deepEqual(calls, [['backend-id', 'confirm'], ['backend-id', 'cancel']])
})

test('completed, failed and rejected cards show outcomes without decision buttons', () => {
  for (const [status, result, text] of [
    ['completed', { success: true, message: 'Activity created.' }, 'Activity created.'],
    ['failed', { success: false, message: 'Outcome unconfirmed.' }, 'Outcome unconfirmed.'],
    ['rejected', null, 'Cancelled. No action was executed.'],
  ]) {
    const html = renderToStaticMarkup(jsx(Card, { proposal: { ...proposal, status, result } }))
    assert.ok(html.includes(text))
    assert.doesNotMatch(html, /<button/)
  }
})

test('both controls are disabled while a decision is pending', () => {
  const html = renderToStaticMarkup(jsx(Card, { proposal, busy: true, disabled: false }))
  assert.equal((html.match(/disabled=""/g) || []).length, 2)
  assert.match(html, /Sending your decision/)
})

test('a refused deletion shows its safe backend error without rendering HTML', () => {
  const html = renderToStaticMarkup(jsx(Card, { proposal: {
    ...proposal, display_title: 'Delete Activity', status: 'failed',
    result: { success: false, message: 'This execution attempt did not run the action.',
      error: 'Activity no longer exists. <Request a new proposal.>' },
  } }))
  assert.match(html, /Activity no longer exists/)
  assert.match(html, /&lt;Request a new proposal.&gt;/)
  assert.doesNotMatch(html, /<button/)
})
