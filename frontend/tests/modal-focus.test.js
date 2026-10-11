import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function harness() {
  const listeners = new Map(), refs = [], effects = []
  let cursor = 0
  const document = { activeElement: null, body: { style: { overflow: 'auto' } },
    addEventListener(type, callback) { listeners.set(type, callback) },
    removeEventListener(type) { listeners.delete(type) } }
  const makeItem = () => ({ hidden: false, isConnected: true, getClientRects: () => [1],
    focus() { document.activeElement = this } })
  const previous = makeItem(), first = makeItem(), last = makeItem()
  previous.focus()
  const dialog = { querySelectorAll: () => [first, last], contains: element => [first, last, dialog].includes(element),
    focus() { document.activeElement = this } }
  const context = vm.createContext({ document,
    useRef(value) { return refs[cursor++] ||= { current: value } },
    useEffect(callback) { effects.push(callback) } })
  const source = fs.readFileSync(new URL('../src/hooks/useModalFocus.js', import.meta.url), 'utf8')
    .replace(/^import .*\n/, '').replace('export default function', 'function')
  vm.runInContext(source, context)
  let closes = 0
  const ref = context.useModalFocus(true, () => closes++)
  ref.current = dialog
  effects[0]()
  const cleanup = effects[1]()
  function press(key, shiftKey = false) {
    const event = { key, shiftKey, prevented: false,
      preventDefault() { this.prevented = true }, stopImmediatePropagation() {} }
    listeners.get('keydown')(event)
    return event
  }
  return { document, first, last, previous, cleanup, press, closed: () => closes,
    busy() { cursor = 0; effects.length = 0; context.useModalFocus(true, () => closes++, true); effects[0]() } }
}

test('dialog focuses its first control, traps Tab and restores focus/scroll on close', () => {
  const h = harness()
  assert.equal(h.document.activeElement, h.first)
  assert.equal(h.document.body.style.overflow, 'hidden')
  h.last.focus()
  assert.equal(h.press('Tab').prevented, true)
  assert.equal(h.document.activeElement, h.first)
  h.press('Tab', true)
  assert.equal(h.document.activeElement, h.last)
  h.cleanup()
  assert.equal(h.document.activeElement, h.previous)
  assert.equal(h.document.body.style.overflow, 'auto')
})

test('Escape closes a dialog but does not dismiss it during a save', () => {
  const h = harness()
  h.press('Escape')
  assert.equal(h.closed(), 1)
  h.busy()
  h.press('Escape')
  assert.equal(h.closed(), 1)
  h.cleanup()
})
