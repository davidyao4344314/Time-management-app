import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformWithOxc } from 'vite'
import { pageFromUrl, urlForPage } from '../src/navigation.js'
import { groupActionProposals } from '../src/components/proposalDisplay.js'
import { hasTimeRange, layoutCalendarDay } from '../src/pages/calendarDisplay.js'

async function component(path, globals = {}) {
  const source = fs.readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const transformed = await transformWithOxc(source, path)
  const context = vm.createContext({ _jsx: jsx, _jsxs: jsxs, _Fragment: Fragment, ...globals })
  vm.runInContext(transformed.code.replace(/^import .*$/gm, '').replace('export default function', 'function')
    .replace(/^export default \w+;?$/gm, ''), context)
  return context
}

test('each navigation page survives refresh with a distinct URL', () => {
  for (const page of ['Home', 'Activities', 'Calendar', 'Exams', 'Screen Time', 'AI Agent', 'AI Settings']) {
    const url = urlForPage('http://localhost:5173/?chat=saved-chat&other=keep', page)
    assert.equal(pageFromUrl(url), page)
    assert.equal(url.searchParams.get('other'), 'keep')
    assert.equal(url.searchParams.has('chat'), page === 'AI Agent')
  }
})

test('legacy chat links and unknown pages remain safe', () => {
  assert.equal(pageFromUrl(new URL('http://localhost/?chat=saved')), 'AI Agent')
  assert.equal(pageFromUrl(new URL('http://localhost/?page=not-a-page')), 'Home')
  assert.equal(pageFromUrl(new URL('http://localhost/?page=exams&chat=old')), 'Exams')
})

test('calendar separates untimed and invalid ranges without assigning fake times', () => {
  const events = [
    { name: 'Date only', startTime: null, endTime: null },
    { name: 'One missing time', startTime: '10:00', endTime: null },
    { name: 'Zero duration', startTime: '07:30', endTime: '07:30' },
    { name: 'Invalid', startTime: '25:00', endTime: '26:00' },
    { name: 'Timed', startTime: '10:00', endTime: '11:00' },
  ]
  const before = structuredClone(events)
  const layout = layoutCalendarDay(events)
  assert.equal(layout.untimed.length, 4)
  assert.equal(layout.timed.length, 1)
  assert.equal(layout.timed[0].laneCount, 1)
  assert.equal(hasTimeRange(events[3]), false)
  assert.deepEqual(events, before)
})

test('overlapping activity and exam blocks get separate lanes; touching ranges do not', () => {
  const events = [
    { name: 'Class', startTime: '09:00', endTime: '12:00', eventType: 'activity' },
    { name: 'Exam', startTime: '10:00', endTime: '11:00', eventType: 'exam' },
    { name: 'Other', startTime: '10:30', endTime: '11:30' },
    { name: 'Lunch', startTime: '12:00', endTime: '13:00' },
  ]
  const before = structuredClone(events)
  const { timed } = layoutCalendarDay(events)
  assert.deepEqual(timed.map(item => [item.lane, item.laneCount]), [[0, 3], [1, 3], [2, 3], [0, 1]])
  assert.equal(timed[1].eventType, 'exam')
  assert.deepEqual(events, before)
})

test('overlap chains reuse a freed lane without obscuring any time interval', () => {
  const { timed } = layoutCalendarDay([
    { name: 'A', startTime: '09:00', endTime: '10:00' },
    { name: 'B', startTime: '09:30', endTime: '10:30' },
    { name: 'C', startTime: '10:00', endTime: '11:00' },
  ])
  assert.deepEqual(timed.map(item => [item.lane, item.laneCount]), [[0, 2], [1, 2], [0, 2]])
})

test('pending proposals attach only to a matching reply in the current conversation', () => {
  const proposals = [
    { id: 'linked', status: 'pending_approval', conversation_id: 'current', request_id: 'request' },
    { id: 'older', status: 'pending_approval', conversation_id: 'current', request_id: 'not-loaded' },
    { id: 'other', status: 'pending_approval', conversation_id: 'other', request_id: 'request' },
    { id: 'standalone', status: 'pending_approval', conversation_id: null },
    { id: 'done', status: 'completed', conversation_id: 'current', request_id: 'request' },
  ]
  const result = groupActionProposals(proposals, 'current', [{ role: 'assistant', request_id: 'request' }])
  assert.deepEqual(result.byRequest.get('request').map(item => item.id), ['linked'])
  assert.deepEqual(result.pending.map(item => item.id), ['older'])
  assert.deepEqual(result.other.map(item => item.id), ['other', 'standalone'])
  assert.deepEqual(result.history.map(item => item.id), ['done'])
  assert.equal(groupActionProposals(proposals, null, []).byRequest.size, 0)
})

const proposalPanel = (await component('components/ActionProposalPanel.jsx', {
  ActionProposalCard: ({ proposal }) => jsx('article', { children: proposal.display_title }),
})).ActionProposalPanel
test('proposal history starts collapsed and identifies another conversation without executing actions', () => {
  const proposal = { id: 'other', status: 'pending_approval', conversation_id: 'other', display_title: 'Review this change' }
  const html = renderToStaticMarkup(jsx(proposalPanel, {
    state: { proposals: [proposal], loading: false, busyId: null, needsRefresh: false, error: '' },
    groups: { pending: [], other: [proposal], history: [] },
    chats: [{ conversation_id: 'other', title: 'Physics plan' }],
  }))
  assert.match(html, /More proposals and history \(1\)/)
  assert.match(html, /From: Physics plan/)
  assert.doesNotMatch(html, /<details open/)
})

test('pending proposals from an unloaded reply open the review panel', () => {
  const proposal = { id: 'older', status: 'pending_approval', conversation_id: 'current', display_title: 'Review older proposal' }
  const html = renderToStaticMarkup(jsx(proposalPanel, {
    state: { proposals: [proposal], loading: false, busyId: null, error: '' },
    groups: { pending: [proposal], other: [], history: [] }, chats: [],
  }))
  assert.match(html, /<details open=""/)
  assert.match(html, /Review older proposal/)
})

const formatter = (await component('components/chat/FormattedMessage.jsx')).FormattedMessage
test('AI response formatting supports bold, code, headings and lists', () => {
  const html = renderToStaticMarkup(jsx(formatter, { text: '### Study plan\n\n**Tonight**\n- Revise `COMPSCI`\n- Take a break\n\n1. Practice\n2. Review' }))
  assert.match(html, /<h3>Study plan<\/h3>/)
  assert.match(html, /<strong>Tonight<\/strong>/)
  assert.match(html, /<code>COMPSCI<\/code>/)
  assert.match(html, /<ul>/)
  assert.match(html, /<ol>/)
  assert.doesNotMatch(html, /\*\*Tonight\*\*/)
})

test('model-supplied HTML, scripts and malicious links stay inert escaped text', () => {
  const html = renderToStaticMarkup(jsx(formatter, { text: '<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n[click](javascript:alert(1))' }))
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script|<img|<a /)
})

test('Home shows real daily data and handles untimed activities', async () => {
  let cursor = 0, mount
  const values = [], calls = []
  const context = await component('pages/Home.jsx', {
    AbortController,
    useState(initial) { const index = cursor++; if (!(index in values)) values[index] = initial
      return [values[index], value => { values[index] = value }] },
    useEffect(callback) { mount ||= callback },
    setInterval() { return 1 }, clearInterval() {},
    async fetch(path) { calls.push(path); return { ok: true, json: async () => path.endsWith('/today')
      ? [{ id: 1, name: 'Real untimed study', subject: 'COMPSCI 130', start_time: null, end_time: null }]
      : { current: null, next: null } } },
  })
  const render = () => { cursor = 0; return renderToStaticMarkup(jsx(context.Home, {})) }
  assert.match(render(), /Loading today/)
  const cleanup = mount()
  await new Promise(resolve => setImmediate(resolve))
  const html = render()
  assert.deepEqual(calls.sort(), ['/api/activities/current-next', '/api/activities/today'])
  assert.match(html, /Real untimed study/)
  assert.match(html, /No time set/)
  assert.doesNotMatch(html, /Physics study|Lunch break|Maths revision/)
  cleanup()
})
