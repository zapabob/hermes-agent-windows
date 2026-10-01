import { AssistantRuntimeProvider, type ThreadMessage, useComposerRuntime, useExternalStoreRuntime } from '@assistant-ui/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import { MemoryRouter } from 'react-router'

import { ChatBar } from '@/app/chat/composer'
import { useSlashCommand } from '@/app/session/hooks/use-prompt-actions/slash'
import { useI18n } from '@/i18n'
import { createClientSessionState } from '@/lib/chat-runtime'
import { queryClient } from '@/lib/query-client'
import { $gatewayState } from '@/store/session'

export interface ComposerEffects {
  draftText: string
  submissions: string[]
  rpc: { method: string; params?: Record<string, unknown> }[]
  outputs: { runtime: string; text: string; stored?: string | null }[]
}

export function prepareComposerFixture() {
  queryClient.clear()
  queryClient.setQueryData(['slash-completions', 'catalog'], {
    commands: { '/f04c-effect': { desktop: 'hidden', argument_mode: 'text' } }
  })
  $gatewayState.set('open')
}

// Only the transport boundary is scripted. Composition handling, rich editor,
// draft flushing, submit engine, and slash routing are production components.
function Composer({ effects }: { effects: ComposerEffects }) {
  const { t } = useI18n()
  const composerRuntime = useComposerRuntime()
  useEffect(() => {
    const observe = () => { effects.draftText = composerRuntime.getState().text }
    observe()

    return composerRuntime.subscribe(observe)
  }, [composerRuntime, effects])

  const slash = useSlashCommand({
    activeSessionIdRef: { current: 'f04c-runtime' },
    selectedStoredSessionIdRef: { current: 'f04c-stored' },
    busyRef: { current: false },
    copy: t.desktop,
    requestGateway: async <T,>(method: string, params?: Record<string, unknown>): Promise<T> => {
      effects.rpc.push({ method, params })

      return { output: 'owned slash result 日本語' } as T
    },
    appendSessionTextMessage: (runtime, _role, text, stored) => {
      effects.outputs.push({ runtime, text, stored })
    },
    branchCurrentSession: async () => true,
    createBackendSessionForSend: async () => { throw new Error('unexpected session creation') },
    getRoutedStoredSessionId: () => null,
    getRuntimeIdForStoredSession: () => null,
    handleSkinCommand: () => '',
    handoffSession: async () => ({ ok: true }),
    openMemoryGraph: () => undefined,
    refreshSessions: async () => undefined,
    resumeStoredSession: () => undefined,
    startFreshSessionDraft: () => undefined,
    submitPromptText: async () => true,
    updateSessionState: (_id, update) => update(createClientSessionState())
  })

  return <ChatBar
    busy={false} disabled={false} onCancel={() => undefined} onSubmit={async text => {
      effects.submissions.push(text)

      if (text.startsWith('/')) {await slash(text, { sessionId: 'f04c-explicit-runtime' })}

      return true
    }}
    queueSessionKey="f04c-owned-queue"
    sessionId="f04c-runtime"
    state={{ model: { model: 'owned-fixture', provider: 'owned-fixture', canSwitch: false },
      tools: { enabled: false, label: '' }, voice: { enabled: false, active: false } }}
  />
}

export function ComposerFixture({ effects }: { effects: ComposerEffects }) {
  const runtime = useExternalStoreRuntime<ThreadMessage>({ messages: [], isRunning: false, onNew: async () => {} })

  return <MemoryRouter><QueryClientProvider client={queryClient}>
    <AssistantRuntimeProvider runtime={runtime}><Composer effects={effects} /></AssistantRuntimeProvider>
  </QueryClientProvider></MemoryRouter>
}
