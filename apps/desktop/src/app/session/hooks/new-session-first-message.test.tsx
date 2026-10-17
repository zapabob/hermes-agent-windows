import { useStore } from '@nanostores/react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { useEffect, useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getLatestSessionMessages } from '@/hermes'
import type { ChatMessage } from '@/lib/chat-messages'
import type * as GatewayStore from '@/store/gateway'
import { requestGatewayForProfile } from '@/store/gateway'
import {
  $activeSessionId,
  $awaitingResponse,
  $busy,
  $messages,
  $selectedStoredSessionId,
  setActiveSessionId,
  setAwaitingResponse,
  setBusy,
  setCurrentFastMode,
  setCurrentModel,
  setCurrentModelSource,
  setCurrentProvider,
  setCurrentReasoningEffort,
  setMessages,
  setSelectedStoredSessionId,
  setSessions
} from '@/store/session'

import { usePromptActions } from './use-prompt-actions'
import { clearSingleFlightSessionResumeState } from './use-prompt-actions/single-flight-resume'
import { useSessionActions } from './use-session-actions'
import { useSessionStateCache } from './use-session-state-cache'

// New sessions use the current profile socket for resume and transcript reads.
vi.mock('@/store/gateway', async importOriginal => ({
  ...(await importOriginal<typeof GatewayStore>()),
  requestGatewayForProfile: vi.fn()
}))
vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getAllSessionMessages: vi.fn(),
  getLatestSessionMessages: vi.fn()
}))

const PROMPT = 'Plan my week.\n\nAbout me:\n- Call me Sid.'
const RUNTIME_ID = 'rt-new'
const STORED_ID = 'stored-new'

type SessionActionsOptions = Parameters<typeof useSessionActions>[0]
type PromptActionsOptions = Parameters<typeof usePromptActions>[0]

interface Ready {
  resume: ReturnType<typeof useSessionActions>['resumeSession']
  submitText: ReturnType<typeof usePromptActions>['submitText']
}

function Harness({
  onReady,
  requestGateway
}: {
  onReady: (ready: Ready) => void
  requestGateway: SessionActionsOptions['requestGateway']
}) {
  const activeSessionId = useStore($activeSessionId)
  const selectedStoredSessionId = useStore($selectedStoredSessionId)
  const busyRef = useRef(false)
  const creatingSessionRef = useRef(false)

  const cache = useSessionStateCache({
    activeSessionId,
    busyRef,
    selectedStoredSessionId,
    setAwaitingResponse,
    setBusy,
    setMessages
  })

  const sessionActions = useSessionActions({
    activeSessionId,
    activeSessionIdRef: cache.activeSessionIdRef,
    busyRef,
    creatingSessionRef,
    ensureSessionState: cache.ensureSessionState,
    getRouteToken: () => 'new-session',
    getRoutedStoredSessionId: () => null,
    navigate: () => {},
    requestGateway,
    resetViewSync: cache.resetViewSync,
    runtimeIdByStoredSessionIdRef: cache.runtimeIdByStoredSessionIdRef,
    selectedStoredSessionId,
    selectedStoredSessionIdRef: cache.selectedStoredSessionIdRef,
    sessionStateByRuntimeIdRef: cache.sessionStateByRuntimeIdRef,
    syncSessionStateToView: cache.syncSessionStateToView,
    updateSessionState: cache.updateSessionState
  })

  const promptActions = usePromptActions({
    activeSessionId,
    activeSessionIdRef: cache.activeSessionIdRef,
    branchCurrentSession: async () => true,
    busyRef,
    createBackendSessionForSend: sessionActions.createBackendSessionForSend,
    getRoutedStoredSessionId: () => null,
    getRuntimeIdForStoredSession: cache.getRuntimeIdForStoredSession,
    getRouteToken: () => 'new-session',
    handleSkinCommand: () => '',
    openMemoryGraph: () => undefined,
    refreshSessions: async () => undefined,
    requestGateway,
    resumeStoredSession: sessionActions.resumeSession,
    runtimeIdByStoredSessionIdRef: cache.runtimeIdByStoredSessionIdRef,
    selectedStoredSessionIdRef: cache.selectedStoredSessionIdRef,
    startFreshSessionDraft: sessionActions.startFreshSessionDraft,
    sttEnabled: false,
    updateSessionState: cache.updateSessionState
  })

  useEffect(() => {
    onReady({
      resume: sessionActions.resumeSession,
      submitText: promptActions.submitText
    })
  }, [cache.sessionStateByRuntimeIdRef, onReady, promptActions.submitText, sessionActions.resumeSession])

  return null
}

const userRows = (messages: readonly ChatMessage[]) => messages.filter(message => message.role === 'user')

const ACTIVATED = {
  info: {},
  message_count: 0,
  messages: [],
  messages_omitted: true,
  resumed: STORED_ID,
  running: true,
  session_id: RUNTIME_ID,
  session_key: STORED_ID
}

let persisted: object[] = []

async function mount({ rejectPromptSubmit = false }: { rejectPromptSubmit?: boolean } = {}) {
  const calls: Array<[string, Record<string, unknown> | undefined]> = []
  vi.mocked(getLatestSessionMessages).mockResolvedValue({
    messages: persisted,
    session_id: STORED_ID
  } as never)

  const requestGateway: SessionActionsOptions['requestGateway'] = async <T,>(
    method: string,
    params?: Record<string, unknown>
  ) => {
    calls.push([method, params])

    if (rejectPromptSubmit && method === 'prompt.submit') {
      throw new Error('prompt.submit refused for test')
    }

    const answer =
      method === 'session.create'
        ? { session_id: RUNTIME_ID, stored_session_id: STORED_ID }
        : method === 'session.activate' || method === 'session.resume'
          ? ACTIVATED
          : {}

    // SAFETY: each result above is the declared wire shape for its request.
    return answer as T
  }

  let ready!: Ready
  const onReady = (value: Ready) => (ready = value)
  render(<Harness onReady={onReady} requestGateway={requestGateway} />)
  await waitFor(() => expect(ready).toBeDefined())
  vi.mocked(requestGatewayForProfile).mockImplementation((_profile, method, params) => requestGateway(method, params))

  return { calls, ready }
}

describe('new-session first prompt and model selection', () => {
  beforeEach(() => {
    persisted = []
    setAwaitingResponse(false)
    setBusy(false)
    setCurrentModel('')
    setCurrentProvider('')
    setCurrentModelSource('')
    setCurrentReasoningEffort('')
    setCurrentFastMode(false)
  })

  afterEach(() => {
    cleanup()
    clearSingleFlightSessionResumeState()
    setActiveSessionId(null)
    setSelectedStoredSessionId(null)
    setAwaitingResponse(false)
    setBusy(false)
    setMessages([])
    setSessions([])
    vi.restoreAllMocks()
  })

  it('sends a manual model and provider, then keeps the first prompt through warm resume', async () => {
    setCurrentModel('anthropic/claude-sonnet-4.6')
    setCurrentProvider('anthropic')
    setCurrentModelSource('manual')
    setCurrentReasoningEffort('high')

    const { calls, ready } = await mount()

    await act(async () => {
      await expect(ready.submitText(PROMPT)).resolves.toBe(true)
    })

    const create = calls.find(([method]) => method === 'session.create')
    expect(create?.[1]).toMatchObject({
      model: 'anthropic/claude-sonnet-4.6',
      provider: 'anthropic',
      reasoning_effort: 'high'
    })
    expect(calls).toContainEqual(['prompt.submit', { session_id: RUNTIME_ID, text: PROMPT }])

    await act(async () => {
      await ready.resume(STORED_ID, true)
    })

    await waitFor(() => expect(userRows($messages.get())).toHaveLength(1))
    expect($activeSessionId.get()).toBe(RUNTIME_ID)
    expect(userRows($messages.get())[0]?.parts).toEqual([expect.objectContaining({ text: PROMPT, type: 'text' })])
  })

  it('does not pin model or provider values that mirror the profile default', async () => {
    setCurrentModel('openai/gpt-5.5')
    setCurrentProvider('openai-codex')
    setCurrentModelSource('default')
    setCurrentReasoningEffort('low')
    setCurrentFastMode(true)

    const { calls, ready } = await mount()

    await act(async () => {
      await expect(ready.submitText('Use the profile default.')).resolves.toBe(true)
    })

    const create = calls.find(([method]) => method === 'session.create')
    expect(create?.[1]).not.toHaveProperty('model')
    expect(create?.[1]).not.toHaveProperty('provider')
    expect(create?.[1]).toMatchObject({ fast: true, reasoning_effort: 'low' })
    expect(calls).toContainEqual(['prompt.submit', { session_id: RUNTIME_ID, text: 'Use the profile default.' }])
  })

  it('retains the first prompt with a visible error when prompt.submit is refused', async () => {
    const { calls, ready } = await mount({ rejectPromptSubmit: true })

    await act(async () => {
      await expect(ready.submitText(PROMPT)).resolves.toBe(false)
    })

    expect(calls).toContainEqual(['prompt.submit', { session_id: RUNTIME_ID, text: PROMPT }])
    expect(userRows($messages.get())).toHaveLength(1)
    expect(userRows($messages.get())[0]?.parts).toEqual([expect.objectContaining({ text: PROMPT, type: 'text' })])
    expect($messages.get().filter(message => message.role === 'assistant' && message.error)).toHaveLength(1)
    expect($busy.get()).toBe(false)
    expect($awaitingResponse.get()).toBe(false)
  })

  it('keeps one first user message when the persisted transcript already contains it', async () => {
    persisted = [{ content: PROMPT, role: 'user', timestamp: 1 }]
    const { ready } = await mount()

    await act(async () => {
      await expect(ready.submitText(PROMPT)).resolves.toBe(true)
    })
    await act(async () => {
      await ready.resume(STORED_ID, true)
    })

    await waitFor(() => expect(getLatestSessionMessages).toHaveBeenCalled())
    await waitFor(() => expect(userRows($messages.get())).toHaveLength(1))
  })
})
