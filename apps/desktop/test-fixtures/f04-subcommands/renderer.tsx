import { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { useComposerTrigger } from '@/app/chat/composer/hooks/use-composer-trigger'
import { useSlashCompletions } from '@/app/chat/composer/hooks/use-slash-completions'
import { composerPlainText, placeCaretAtOffset, renderComposerContents } from '@/app/chat/composer/rich-editor'
import { usePromptActions } from '@/app/session/hooks/use-prompt-actions'
import type { ClientSessionState } from '@/app/types'
import type { HermesGateway } from '@/hermes'
import { $activeGatewayProfile } from '@/store/profile'

interface ReviewProbe {
  select: (profile: string, storedId: string) => void
  load: (text: string) => void
  rows: () => string[]
  pick: (command: string) => void
  submit: () => Promise<boolean>
  text: () => string
  messages: () => unknown[]
}

declare global {
  interface Window {
    reviewProbe: ReviewProbe
  }
}

function Probe() {
  const editorRef = useRef<HTMLDivElement>(null)
  const draftRef = useRef('')
  const runtime = useRef<string | null>('f04-runtime-owner')
  const stored = useRef<string | null>('f04-stored-owner')
  const busy = useRef(false)
  const states = useRef(new Map<string, ClientSessionState>())
  const [, setText] = useState('')
  const sequence = useRef(0)

  const request = async <T,>(method: string, params?: Record<string, unknown>): Promise<T> => {
    const response = await fetch('/fixture/rpc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: ++sequence.current, method, params: params ?? {} })
    })

    const envelope = await response.json()

    if (envelope.error) {
      throw new Error(JSON.stringify(envelope.error))
    }

    return envelope.result as T
  }

  const [gateway] = useState(() => ({ request }) as unknown as HermesGateway)
  const slash = useSlashCompletions({ gateway })

  const trigger = useComposerTrigger({
    editorRef,
    draftRef,
    at: { adapter: null, loading: false },
    slash,
    requestMainFocus: () => editorRef.current?.focus(),
    setComposerText: setText
  })

  const actions = usePromptActions({
    activeSessionId: runtime.current,
    activeSessionIdRef: runtime,
    busyRef: busy,
    branchCurrentSession: async () => true,
    createBackendSessionForSend: async () => runtime.current,
    getRoutedStoredSessionId: () => stored.current,
    getRuntimeIdForStoredSession: () => runtime.current,
    getRouteToken: () => runtime.current ?? '',
    handleSkinCommand: () => '',
    openMemoryGraph: () => {},
    refreshSessions: async () => {},
    requestGateway: request,
    resumeStoredSession: () => {},
    runtimeIdByStoredSessionIdRef: { current: new Map() },
    selectedStoredSessionIdRef: stored,
    startFreshSessionDraft: () => {},
    sttEnabled: false,
    updateSessionState: (id, updater) => {
      const previous = states.current.get(id) ?? ({ messages: [], busy: false } as ClientSessionState)
      const next = updater(previous)
      states.current.set(id, next)

      return next
    }
  })

  window.reviewProbe = {
    select: (profile, storedId) => {
      runtime.current = `f04-runtime-${profile}`
      stored.current = storedId
      $activeGatewayProfile.set(`f04-${profile}`)
      setText('')
    },
    load: text => {
      const editor = editorRef.current!
      renderComposerContents(editor, text)
      draftRef.current = text
      editor.focus()
      placeCaretAtOffset(editor, text.length)
      trigger.refreshTrigger()
    },
    rows: () => trigger.triggerItems.map(row => (row.metadata as { command: string }).command),
    pick: command => {
      const item = trigger.triggerItems.find(row => (row.metadata as { command?: string })?.command === command)

      if (!item) {
        throw new Error(`missing actual accepted completion: ${command}`)
      }

      trigger.replaceTriggerWithChip(item)
    },
    submit: () => actions.submitText(composerPlainText(editorRef.current!)),
    text: () => composerPlainText(editorRef.current!),
    messages: () => states.current.get(runtime.current!)?.messages ?? []
  }

  return (
    <div
      contentEditable
      data-testid="editor"
      onInput={() => trigger.refreshTrigger()}
      ref={editorRef}
      suppressContentEditableWarning
    />
  )
}

createRoot(document.getElementById('root')!).render(<Probe />)
