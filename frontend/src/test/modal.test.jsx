/**
 * Confirmation dialog behaviour: focus moves in, Tab is trapped, Escape closes
 * and focus returns to whatever opened it. A dialog that forgets this strands
 * keyboard users behind the backdrop.
 */

import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Modal from '../components/Modal'

function Harness({ open = true, onClose = () => {} }) {
  return (
    <Modal
      open={open}
      title="Delete this exam?"
      onClose={onClose}
      footer={
        <>
          <button type="button">Cancel</button>
          <button type="button">Delete exam</button>
        </>
      }
    >
      <p>This cannot be undone.</p>
    </Modal>
  )
}

/** Opens the dialog from a real trigger button so focus restoration is testable. */
function HarnessWithTrigger() {
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <Harness open={open} onClose={() => setOpen(false)} />
    </>
  )
}

describe('Modal', () => {
  it('is announced as a labelled modal dialog', () => {
    render(<Harness />)
    const dialog = screen.getByRole('dialog', { name: 'Delete this exam?' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })

  it('moves focus into the dialog when it opens', async () => {
    render(<Harness />)
    const dialog = screen.getByRole('dialog')
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }))
  })

  it('traps Tab inside the dialog', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const dialog = screen.getByRole('dialog')
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    const confirm = screen.getByRole('button', { name: 'Delete exam' })

    cancel.focus()
    await user.tab()
    expect(document.activeElement).toBe(confirm)
    await user.tab() // wraps back to the first control, not out to the page
    expect(document.activeElement).toBe(cancel)
    expect(dialog.contains(document.activeElement)).toBe(true)

    await user.tab({ shift: true }) // and backwards
    expect(document.activeElement).toBe(confirm)
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('returns focus to the trigger when it closes', async () => {
    const user = userEvent.setup()
    render(<HarnessWithTrigger />)

    const trigger = screen.getByRole('button', { name: 'Open dialog' })
    await user.click(trigger)
    await screen.findByRole('dialog')

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.activeElement).toBe(trigger)
  })
})
