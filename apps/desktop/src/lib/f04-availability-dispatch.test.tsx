import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { useSlashCommand } from '@/app/session/hooks/use-prompt-actions/slash'
import { useI18n } from '@/i18n'
import { createClientSessionState } from '@/lib/chat-runtime'
import { queryClient } from '@/lib/query-client'

afterEach(() => {
  cleanup()
  queryClient.clear()
})

it.each(['hidden', 'terminal', 'messaging', 'advanced'] as const)(
  'public slash caller respects %s metadata and target identity',
  async desktop => {
    queryClient.setQueryData(['slash-completions', 'catalog'], {
      commands: { '/f04-effect': { desktop, argument_mode: 'text' } }
    })
    const output = vi.fn()
    const effects: { method: string; params?: Record<string, unknown> }[] = []

    const requestGateway = async <T,>(method: string, params?: Record<string, unknown>): Promise<T> => {
      effects.push({ method, params })

      return { output: 'test-owned result 日本語' } as T
    }

    const { result } = renderHook(() => {
      const { t } = useI18n()

      return useSlashCommand({
        activeSessionIdRef: { current: 'f04-active-runtime' },
        selectedStoredSessionIdRef: { current: 'f04-selected-stored' },
        busyRef: { current: false },
        copy: t.desktop,
        requestGateway,
        appendSessionTextMessage: output,
        branchCurrentSession: async () => true,
        createBackendSessionForSend: async () => {
          throw new Error('must not mint another session')
        },
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
    })

    await act(async () => {
      await result.current('/f04-effect 日本語の引数', { sessionId: 'f04-explicit-runtime' })
    })

    if (desktop === 'hidden') {
      expect(effects).toEqual([
        { method: 'slash.exec', params: { session_id: 'f04-explicit-runtime', command: 'f04-effect 日本語の引数' } }
      ])
      expect(output).toHaveBeenCalledWith(
        'f04-explicit-runtime',
        'system',
        expect.stringContaining('test-owned result 日本語'),
        'f04-selected-stored'
      )
    } else {
      expect(effects).toEqual([])
      expect(output).toHaveBeenCalledWith(
        'f04-explicit-runtime',
        'system',
        expect.stringContaining('/f04-effect'),
        'f04-selected-stored'
      )
    }
  }
)
