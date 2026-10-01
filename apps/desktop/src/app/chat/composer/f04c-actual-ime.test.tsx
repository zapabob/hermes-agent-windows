import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type ComposerEffects, ComposerFixture, prepareComposerFixture } from '../../../../test-fixtures/f04c-composer/fixture'

afterEach(cleanup)
beforeEach(() => {
  prepareComposerFixture()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
  Range.prototype.getBoundingClientRect = () => new DOMRect()
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList
})

describe('actual ChatBar IME public entry', () => {
  it.each(['確定した日本語', '/f04c-effect 日本語の引数'])('suppresses composing/229 and sends finalized %s exactly once', async text => {
    const effects: ComposerEffects = { draftText: '', submissions: [], rpc: [], outputs: [] }
    const { container } = render(<ComposerFixture effects={effects} />)
    const editor = container.querySelector<HTMLDivElement>('[contenteditable="true"][role="textbox"]')!
    expect(editor).not.toBeNull()
    editor.focus()
    fireEvent.compositionStart(editor)
    editor.textContent = '未確定の日本語'
    fireEvent.input(editor, { inputType: 'insertCompositionText', isComposing: true })
    fireEvent.keyDown(editor, { key: 'Enter', keyCode: 13, isComposing: true })
    expect(effects.submissions).toEqual([])
    expect(effects.rpc).toEqual([])
    fireEvent.keyDown(editor, { key: 'Enter', keyCode: 229, isComposing: true })
    expect(effects.submissions).toEqual([])
    expect(effects.draftText).toBe('')
    editor.textContent = text
    fireEvent.compositionEnd(editor, { data: text })
    await waitFor(() => expect(effects.draftText).toBe(text))
    fireEvent.keyDown(editor, { key: 'Enter', keyCode: 229, isComposing: false })
    expect(effects.submissions).toEqual([])
    expect(effects.rpc).toEqual([])
    await act(async () => { fireEvent.keyDown(editor, { key: 'Enter', keyCode: 13, isComposing: false }) })
    await waitFor(() => expect(effects.submissions).toEqual([text]))
    expect(editor.textContent).toBe('')

    if (text.startsWith('/')) {
      expect(effects.rpc).toEqual([{ method: 'slash.exec', params: {
        session_id: 'f04c-explicit-runtime', command: 'f04c-effect 日本語の引数'
      } }])
      expect(effects.outputs).toEqual([{ runtime: 'f04c-explicit-runtime', text: 'slash:/f04c-effect\nowned slash result 日本語', stored: 'f04c-stored' }])
    } else {
      expect(effects.rpc).toEqual([])
    }
  })
})
