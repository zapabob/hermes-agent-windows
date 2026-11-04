import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSub,
  DropdownMenuSubTrigger
} from '@/components/ui/dropdown-menu'

import { type DaybreakControl, type FastControl, ModelEditSubmenu } from './model-edit-submenu'

// Radix calls these on open; jsdom doesn't implement them.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.releasePointerCapture = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

// Render the submenu inside an open menu/sub so its content (switches) mounts.
function renderSubmenu(opts: {
  daybreak?: DaybreakControl
  defaultEffort?: string
  effort?: string
  fastControl: FastControl
  isActive?: boolean
  onSelectModel?: (model: string) => void
  onSetOptions: (patch: { effort?: string; fast?: boolean }) => void
  reasoning: boolean
}) {
  return render(
    <DropdownMenu open>
      <DropdownMenuContent>
        <DropdownMenuSub open>
          <DropdownMenuSubTrigger>edit</DropdownMenuSubTrigger>
          <ModelEditSubmenu
            daybreak={opts.daybreak}
            defaultEffort={opts.defaultEffort ?? 'medium'}
            effort={opts.effort ?? 'medium'}
            fastControl={opts.fastControl}
            isActive={opts.isActive ?? true}
            model="m1"
            onSelectModel={opts.onSelectModel ?? vi.fn()}
            onSetOptions={opts.onSetOptions}
            provider="p1"
            reasoning={opts.reasoning}
          />
        </DropdownMenuSub>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// The submenu is PURE: it reports edits and never writes to a session, a
// preset store, or the gateway. That's the invariant that lets the same
// component drive a live chat session AND a detached per-task override — if it
// ever writes directly again, picking an effort for a kanban card would reach
// over and change the user's live chat.
describe('ModelEditSubmenu reports edits without performing them', () => {
  it('Daybreak changes only the profile switch, even without fast or reasoning controls', () => {
    const set = vi.fn()
    const onSetOptions = vi.fn()
    const onSelectModel = vi.fn()
    renderSubmenu({
      daybreak: { on: true, set },
      fastControl: { kind: 'none' },
      onSelectModel,
      onSetOptions,
      reasoning: false
    })

    fireEvent.click(screen.getByRole('switch', { name: 'Daybreak' }))

    expect(set).toHaveBeenCalledWith(false)
    expect(onSetOptions).not.toHaveBeenCalled()
    expect(onSelectModel).not.toHaveBeenCalled()
  })

  it('keeps Daybreak, Fast Mode and reasoning effort independent', () => {
    const set = vi.fn()
    const onSetOptions = vi.fn()
    renderSubmenu({
      daybreak: { on: false, set },
      fastControl: { kind: 'param', on: false },
      onSetOptions,
      reasoning: true
    })

    fireEvent.click(screen.getByRole('switch', { name: 'Daybreak' }))
    expect(set).toHaveBeenCalledWith(true)
    expect(onSetOptions).not.toHaveBeenCalled()

    fireEvent.click(
      screen.getAllByRole('switch').find(node => node.closest('[role="menuitem"]')?.textContent === 'Fast')!
    )
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'High' }))
    expect(onSetOptions.mock.calls).toEqual([[{ fast: true }], [{ effort: 'high' }]])
    expect(set).toHaveBeenCalledTimes(1)
  })

  it('cannot write Daybreak before the owner value has loaded', () => {
    const set = vi.fn()
    renderSubmenu({
      daybreak: { disabled: true, on: false, set },
      fastControl: { kind: 'none' },
      onSetOptions: vi.fn(),
      reasoning: false
    })
    const toggle = screen.getByRole('switch', { name: 'Daybreak' })
    expect(toggle.hasAttribute('disabled')).toBe(true)
    fireEvent.click(toggle)
    expect(set).not.toHaveBeenCalled()
  })

  it('param fast: reports the toggle', () => {
    const onSetOptions = vi.fn()
    renderSubmenu({ fastControl: { kind: 'param', on: true }, onSetOptions, reasoning: false })

    fireEvent.click(screen.getByRole('switch'))

    expect(onSetOptions).toHaveBeenCalledWith({ fast: false })
  })

  it('thinking: toggling off reports the none level', () => {
    const onSetOptions = vi.fn()
    renderSubmenu({ fastControl: { kind: 'none' }, onSetOptions, reasoning: true })

    // Thinking starts on (medium); toggling it off reports 'none'.
    fireEvent.click(screen.getByRole('switch'))

    expect(onSetOptions).toHaveBeenCalledWith({ effort: 'none' })
  })

  it('thinking: toggling back on restores the row level, not the hardcoded default', () => {
    const onSetOptions = vi.fn()
    renderSubmenu({
      defaultEffort: 'high',
      effort: 'none',
      fastControl: { kind: 'none' },
      onSetOptions,
      reasoning: true
    })

    fireEvent.click(screen.getByRole('switch'))

    expect(onSetOptions).toHaveBeenCalledWith({ effort: 'high' })
  })

  it('variant fast: swaps the model only when the row is active', () => {
    const onSelectModel = vi.fn()
    const onSetOptions = vi.fn()

    renderSubmenu({
      fastControl: { baseId: 'm1', fastId: 'm1-fast', kind: 'variant', on: false },
      isActive: false,
      onSelectModel,
      onSetOptions,
      reasoning: false
    })

    fireEvent.click(screen.getByRole('switch'))

    // Inactive rows stay preference-only — no model switch.
    expect(onSetOptions).toHaveBeenCalledWith({ fast: true })
    expect(onSelectModel).not.toHaveBeenCalled()
  })

  it('variant fast: active row swaps to the -fast sibling', () => {
    const onSelectModel = vi.fn()
    const onSetOptions = vi.fn()

    renderSubmenu({
      fastControl: { baseId: 'm1', fastId: 'm1-fast', kind: 'variant', on: false },
      onSelectModel,
      onSetOptions,
      reasoning: false
    })

    fireEvent.click(screen.getByRole('switch'))

    expect(onSelectModel).toHaveBeenCalledWith('m1-fast')
  })
})
