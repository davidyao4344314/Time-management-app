import { useEffect, useRef } from 'react'

// Shared keyboard behavior for existing dialogs; no changes to save logic.
export default function useModalFocus(open, onClose, busy = false) {
  const dialog = useRef(null)
  const close = useRef(onClose)
  const saving = useRef(busy)
  useEffect(() => { close.current = onClose; saving.current = busy }, [onClose, busy])

  useEffect(() => {
    if (!open || !dialog.current) return
    const previous = document.activeElement
    const element = dialog.current
    const overflow = document.body.style.overflow
    const focusable = () => [...element.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]',
    )].filter(item => !item.hidden && item.getClientRects().length > 0)
    const focusFirst = () => (focusable()[0] || element).focus()
    document.body.style.overflow = 'hidden'
    focusFirst()
    function keydown(event) {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopImmediatePropagation()
        if (!saving.current) close.current?.()
      }
      if (event.key === 'Tab') {
        const items = focusable()
        const index = items.indexOf(document.activeElement)
        if (!items.length) { event.preventDefault(); element.focus() }
        else if (event.shiftKey && index <= 0) { event.preventDefault(); items.at(-1).focus() }
        else if (!event.shiftKey && (index === -1 || index === items.length - 1)) {
          event.preventDefault(); items[0].focus()
        }
      }
    }
    function keepFocus(event) {
      if (!element.contains(event.target)) focusFirst()
    }
    document.addEventListener('keydown', keydown, true)
    document.addEventListener('focusin', keepFocus)
    return () => {
      document.removeEventListener('keydown', keydown, true)
      document.removeEventListener('focusin', keepFocus)
      document.body.style.overflow = overflow
      if (previous?.isConnected) previous.focus()
    }
  }, [open])
  return dialog
}
