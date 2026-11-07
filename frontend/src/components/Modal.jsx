import { useEffect, useId, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Accessible confirmation dialog.
 *
 * Keyboard behaviour (the part that makes it usable without a mouse):
 *   * Escape closes it.
 *   * Focus moves into the dialog when it opens and returns to the element that
 *     opened it when it closes.
 *   * Tab / Shift+Tab cycle inside the dialog instead of reaching the page
 *     behind it.
 * Clicking the backdrop also closes it.
 */
export default function Modal({ open, title, children, onClose, footer }) {
  const dialogRef = useRef(null)
  const openerRef = useRef(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return undefined

    // Remember where focus came from so it can be restored on close.
    openerRef.current = document.activeElement
    const dialog = dialogRef.current
    const firstFocusable = dialog?.querySelector(FOCUSABLE)
    ;(firstFocusable || dialog)?.focus()

    function onKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialog) return

      // No offsetParent/visibility filtering: it is null for position:fixed
      // dialogs (this one) and in jsdom, which would empty the list and break
      // the wrap-around in exactly the case it is meant to handle.
      const focusable = Array.from(dialog.querySelectorAll(FOCUSABLE))
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      // Wrap around at both ends, and pull focus back if it escaped the dialog.
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      const opener = openerRef.current
      if (opener && typeof opener.focus === 'function') opener.focus()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialogRef}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{title}</h2>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </div>
    </div>
  )
}
