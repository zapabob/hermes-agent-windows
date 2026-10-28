import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getDelegationConfig, saveDelegationConfig } from '@/hermes'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { Users } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { notify, notifyError } from '@/store/notifications'
import { $settingsRequestProfile } from '@/store/settings-scope'

import { useOnProfileSwitch } from '../hooks/use-on-profile-switch'

import { CONTROL_TEXT } from './constants'
import { ListRow, SectionHeading, SettingsContent, ToggleRow } from './primitives'

const REASONING_EFFORTS = ['', 'xhigh', 'high', 'medium', 'low', 'minimal'] as const
const API_MODES = ['', 'chat_completions', 'codex_responses', 'anthropic_messages'] as const

type FallbackMode = 'inherit' | 'disabled' | 'custom'

interface FallbackEntry {
  provider: string
  model: string
}

export interface SubagentDraft {
  model: string
  provider: string
  base_url: string
  api_mode: string
  inherit_mcp_toolsets: boolean
  max_iterations: number
  max_summary_chars: number
  child_timeout_seconds: number
  reasoning_effort: string
  max_concurrent_children: number
  max_spawn_depth: number
  orchestrator_enabled: boolean
  subagent_auto_approve: boolean
  surface_child_process_notifications: boolean
  /** null = inherit (omit); [] = explicitly disabled */
  fallback_providers: null | FallbackEntry[]
}

const DEFAULT_DRAFT: SubagentDraft = {
  model: '',
  provider: '',
  base_url: '',
  api_mode: '',
  inherit_mcp_toolsets: true,
  max_iterations: 250,
  max_summary_chars: 24000,
  child_timeout_seconds: 0,
  reasoning_effort: '',
  max_concurrent_children: 10,
  max_spawn_depth: 1,
  orchestrator_enabled: true,
  subagent_auto_approve: false,
  surface_child_process_notifications: false,
  fallback_providers: null
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asBool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }

  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)

    if (Number.isFinite(parsed)) {
      return parsed
    }
  }

  return fallback
}

function parseFallback(raw: unknown): null | FallbackEntry[] {
  if (raw === undefined) {
    return null
  }

  if (raw === null) {
    return null
  }

  if (!Array.isArray(raw)) {
    return null
  }

  if (raw.length === 0) {
    return []
  }

  const entries: FallbackEntry[] = []

  for (const item of raw) {
    if (typeof item === 'string') {
      const slash = item.indexOf('/')

      if (slash > 0) {
        entries.push({ provider: item.slice(0, slash).trim(), model: item.slice(slash + 1).trim() })
      }

      continue
    }

    if (item && typeof item === 'object') {
      const row = item as Record<string, unknown>
      entries.push({
        provider: asString(row.provider),
        model: asString(row.model)
      })
    }
  }

  return entries
}

export function blockToDraft(block: Record<string, unknown>): SubagentDraft {
  return {
    model: asString(block.model, DEFAULT_DRAFT.model),
    provider: asString(block.provider, DEFAULT_DRAFT.provider),
    base_url: asString(block.base_url, DEFAULT_DRAFT.base_url),
    api_mode: asString(block.api_mode, DEFAULT_DRAFT.api_mode),
    inherit_mcp_toolsets: asBool(block.inherit_mcp_toolsets, DEFAULT_DRAFT.inherit_mcp_toolsets),
    max_iterations: asNumber(block.max_iterations, DEFAULT_DRAFT.max_iterations),
    max_summary_chars: asNumber(block.max_summary_chars, DEFAULT_DRAFT.max_summary_chars),
    child_timeout_seconds: asNumber(block.child_timeout_seconds, DEFAULT_DRAFT.child_timeout_seconds),
    reasoning_effort: asString(block.reasoning_effort, DEFAULT_DRAFT.reasoning_effort),
    max_concurrent_children: asNumber(block.max_concurrent_children, DEFAULT_DRAFT.max_concurrent_children),
    max_spawn_depth: asNumber(block.max_spawn_depth, DEFAULT_DRAFT.max_spawn_depth),
    orchestrator_enabled: asBool(block.orchestrator_enabled, DEFAULT_DRAFT.orchestrator_enabled),
    subagent_auto_approve: asBool(block.subagent_auto_approve, DEFAULT_DRAFT.subagent_auto_approve),
    surface_child_process_notifications: asBool(
      block.surface_child_process_notifications,
      DEFAULT_DRAFT.surface_child_process_notifications
    ),
    fallback_providers: 'fallback_providers' in block ? parseFallback(block.fallback_providers) : null
  }
}

/** Wire payload for PUT — full draft, never includes api_key. */
export function draftToPayload(draft: SubagentDraft): Record<string, unknown> {
  return {
    model: draft.model,
    provider: draft.provider,
    base_url: draft.base_url,
    api_mode: draft.api_mode,
    inherit_mcp_toolsets: draft.inherit_mcp_toolsets,
    max_iterations: draft.max_iterations,
    max_summary_chars: draft.max_summary_chars,
    child_timeout_seconds: draft.child_timeout_seconds,
    reasoning_effort: draft.reasoning_effort,
    max_concurrent_children: draft.max_concurrent_children,
    max_spawn_depth: draft.max_spawn_depth,
    orchestrator_enabled: draft.orchestrator_enabled,
    subagent_auto_approve: draft.subagent_auto_approve,
    surface_child_process_notifications: draft.surface_child_process_notifications,
    fallback_providers: draft.fallback_providers
  }
}

function fallbackModeOf(draft: SubagentDraft): FallbackMode {
  if (draft.fallback_providers === null) {
    return 'inherit'
  }

  if (draft.fallback_providers.length === 0) {
    return 'disabled'
  }

  return 'custom'
}

function draftsEqual(a: SubagentDraft, b: SubagentDraft): boolean {
  return JSON.stringify(draftToPayload(a)) === JSON.stringify(draftToPayload(b))
}

const CAPTION = 'text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)'

export function SubagentSettings() {
  const { t } = useI18n()
  const copy = t.settings.subagent
  const requestProfile = useStore($settingsRequestProfile)

  const profileEpoch = useRef(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasApiKey, setHasApiKey] = useState(false)
  const [baseline, setBaseline] = useState<SubagentDraft>(DEFAULT_DRAFT)
  const [draft, setDraft] = useState<SubagentDraft>(DEFAULT_DRAFT)

  const dirty = useMemo(() => !draftsEqual(draft, baseline), [baseline, draft])

  const load = useCallback(async () => {
    const epoch = profileEpoch.current
    setLoading(true)

    try {
      const res = await getDelegationConfig(requestProfile)

      if (profileEpoch.current !== epoch) {
        return
      }

      const next = blockToDraft(res.delegation ?? {})
      setBaseline(next)
      setDraft(next)
      setHasApiKey(Boolean(res.has_api_key))
    } catch (err) {
      if (profileEpoch.current === epoch) {
        notifyError(err, copy.loadFailed)
      }
    } finally {
      if (profileEpoch.current === epoch) {
        setLoading(false)
      }
    }
  }, [copy.loadFailed, requestProfile])

  useEffect(() => {
    void load()
  }, [load])

  useOnProfileSwitch(() => {
    profileEpoch.current += 1
    setDraft(DEFAULT_DRAFT)
    setBaseline(DEFAULT_DRAFT)
    setHasApiKey(false)
    void load()
  })

  const patch = <K extends keyof SubagentDraft>(key: K, value: SubagentDraft[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  const setFallbackMode = (mode: FallbackMode) => {
    if (mode === 'inherit') {
      patch('fallback_providers', null)

      return
    }

    if (mode === 'disabled') {
      patch('fallback_providers', [])

      return
    }

    const current = draft.fallback_providers
    patch('fallback_providers', current && current.length > 0 ? current : [{ provider: '', model: '' }])
  }

  const apply = async () => {
    if (saving || !dirty) {
      return
    }

    const epoch = profileEpoch.current
    const snapshot = draft
    setSaving(true)

    try {
      const res = await saveDelegationConfig(draftToPayload(snapshot), requestProfile)

      if (profileEpoch.current !== epoch) {
        // Stale Apply after profile switch — discard; do not paint onto new draft.
        return
      }

      const saved = blockToDraft(res.delegation ?? {})
      setBaseline(saved)
      setDraft(saved)
      triggerHaptic('success')
      notify({
        kind: 'info',
        message: res.applies_on === 'new_session' ? copy.savedNewSession : copy.savedNextChild
      })
    } catch (err) {
      if (profileEpoch.current === epoch) {
        // Keep the user's draft so they can fix and retry.
        notifyError(err, copy.saveFailed)
      }
    } finally {
      if (profileEpoch.current === epoch) {
        setSaving(false)
      }
    }
  }

  const mode = fallbackModeOf(draft)

  return (
    <SettingsContent>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3 pt-2">
        <div className="min-w-0 flex-1">
          <SectionHeading icon={Users} title={copy.title} />
          <p className={cn(CAPTION, 'mb-1 leading-(--conversation-caption-line-height)')}>{copy.blurb}</p>
          <p className={cn(CAPTION, 'leading-(--conversation-caption-line-height)')}>{copy.runtimeNote}</p>
          <p className={cn(CAPTION, 'leading-(--conversation-caption-line-height)')}>{copy.schemaNote}</p>
          <p className={cn(CAPTION, 'mt-1 leading-(--conversation-caption-line-height)')}>{copy.secretNote}</p>
          {hasApiKey ? (
            <p className={cn(CAPTION, 'mt-1 leading-(--conversation-caption-line-height)')}>{copy.hasApiKey}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {dirty ? <span className={cn(CAPTION)}>{copy.dirty}</span> : null}
          <Button disabled={!dirty || saving || loading} onClick={() => void apply()} type="button">
            {saving ? copy.applying : copy.apply}
          </Button>
        </div>
      </div>

      <ListRow
        action={
          <Input
            aria-label={copy.provider}
            className={CONTROL_TEXT}
            disabled={loading}
            onChange={e => patch('provider', e.target.value)}
            placeholder="(inherit)"
            value={draft.provider}
          />
        }
        title={copy.provider}
      />
      <ListRow
        action={
          <Input
            aria-label={copy.model}
            className={CONTROL_TEXT}
            disabled={loading}
            onChange={e => patch('model', e.target.value)}
            placeholder="(inherit)"
            value={draft.model}
          />
        }
        title={copy.model}
      />
      <ListRow
        action={
          <Input
            aria-label={copy.baseUrl}
            className={CONTROL_TEXT}
            disabled={loading}
            onChange={e => patch('base_url', e.target.value)}
            placeholder="https://…"
            value={draft.base_url}
          />
        }
        title={copy.baseUrl}
      />
      <ListRow
        action={
          <Select
            disabled={loading}
            onValueChange={v => patch('api_mode', v === '__inherit__' ? '' : v)}
            value={draft.api_mode || '__inherit__'}
          >
            <SelectTrigger aria-label={copy.apiMode} className={cn('min-w-56', CONTROL_TEXT)}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {API_MODES.map(modeValue => (
                <SelectItem key={modeValue || '__inherit__'} value={modeValue || '__inherit__'}>
                  {modeValue || copy.apiModeInherit}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
        title={copy.apiMode}
      />
      <ListRow
        action={
          <Select
            disabled={loading}
            onValueChange={v => patch('reasoning_effort', v === '__inherit__' ? '' : v)}
            value={draft.reasoning_effort || '__inherit__'}
          >
            <SelectTrigger aria-label={copy.reasoningEffort} className={cn('min-w-56', CONTROL_TEXT)}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REASONING_EFFORTS.map(effort => (
                <SelectItem key={effort || '__inherit__'} value={effort || '__inherit__'}>
                  {effort || copy.reasoningInherit}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
        title={copy.reasoningEffort}
      />

      <ListRow
        action={
          <Input
            aria-label={copy.maxIterations}
            className={CONTROL_TEXT}
            disabled={loading}
            min={1}
            onChange={e => patch('max_iterations', Number(e.target.value) || 1)}
            type="number"
            value={draft.max_iterations}
          />
        }
        title={copy.maxIterations}
      />
      <ListRow
        action={
          <Input
            aria-label={copy.maxSummaryChars}
            className={CONTROL_TEXT}
            disabled={loading}
            min={0}
            onChange={e => patch('max_summary_chars', Number(e.target.value) || 0)}
            type="number"
            value={draft.max_summary_chars}
          />
        }
        title={copy.maxSummaryChars}
      />
      <ListRow
        action={
          <Input
            aria-label={copy.childTimeout}
            className={CONTROL_TEXT}
            disabled={loading}
            min={0}
            onChange={e => patch('child_timeout_seconds', Number(e.target.value) || 0)}
            type="number"
            value={draft.child_timeout_seconds}
          />
        }
        title={copy.childTimeout}
      />
      <ListRow
        action={
          <Input
            aria-label={copy.maxConcurrent}
            className={CONTROL_TEXT}
            disabled={loading}
            min={1}
            onChange={e => patch('max_concurrent_children', Number(e.target.value) || 1)}
            type="number"
            value={draft.max_concurrent_children}
          />
        }
        title={copy.maxConcurrent}
      />
      <ListRow
        action={
          <Input
            aria-label={copy.maxSpawnDepth}
            className={CONTROL_TEXT}
            disabled={loading}
            min={1}
            onChange={e => patch('max_spawn_depth', Number(e.target.value) || 1)}
            type="number"
            value={draft.max_spawn_depth}
          />
        }
        title={copy.maxSpawnDepth}
      />

      <ToggleRow
        checked={draft.inherit_mcp_toolsets}
        description={copy.inheritMcpDesc}
        disabled={loading}
        label={copy.inheritMcp}
        onChange={on => patch('inherit_mcp_toolsets', on)}
      />
      <ToggleRow
        checked={draft.orchestrator_enabled}
        description={copy.orchestratorDesc}
        disabled={loading}
        label={copy.orchestrator}
        onChange={on => patch('orchestrator_enabled', on)}
      />
      <ToggleRow
        checked={draft.subagent_auto_approve}
        description={copy.autoApproveDesc}
        disabled={loading}
        label={copy.autoApprove}
        onChange={on => patch('subagent_auto_approve', on)}
      />
      <ToggleRow
        checked={draft.surface_child_process_notifications}
        description={copy.surfaceChildNotifyDesc}
        disabled={loading}
        label={copy.surfaceChildNotify}
        onChange={on => patch('surface_child_process_notifications', on)}
      />

      <ListRow
        action={
          <Select disabled={loading} onValueChange={v => setFallbackMode(v as FallbackMode)} value={mode}>
            <SelectTrigger aria-label={copy.fallbackMode} className={cn('min-w-56', CONTROL_TEXT)}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="inherit">{copy.fallbackInherit}</SelectItem>
              <SelectItem value="disabled">{copy.fallbackDisabled}</SelectItem>
              <SelectItem value="custom">{copy.fallbackCustom}</SelectItem>
            </SelectContent>
          </Select>
        }
        title={copy.fallbackMode}
      />

      {mode === 'custom' && draft.fallback_providers
        ? draft.fallback_providers.map((entry, index) => (
            <ListRow
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    aria-label={`${copy.fallbackProvider} ${index + 1}`}
                    className={cn('min-w-28', CONTROL_TEXT)}
                    disabled={loading}
                    onChange={e => {
                      const next = [...(draft.fallback_providers ?? [])]
                      next[index] = { ...next[index], provider: e.target.value }
                      patch('fallback_providers', next)
                    }}
                    placeholder={copy.fallbackProvider}
                    value={entry.provider}
                  />
                  <Input
                    aria-label={`${copy.fallbackModel} ${index + 1}`}
                    className={cn('min-w-28', CONTROL_TEXT)}
                    disabled={loading}
                    onChange={e => {
                      const next = [...(draft.fallback_providers ?? [])]
                      next[index] = { ...next[index], model: e.target.value }
                      patch('fallback_providers', next)
                    }}
                    placeholder={copy.fallbackModel}
                    value={entry.model}
                  />
                  <Button
                    disabled={loading}
                    onClick={() => {
                      const next = (draft.fallback_providers ?? []).filter((_, i) => i !== index)
                      patch('fallback_providers', next.length ? next : [{ provider: '', model: '' }])
                    }}
                    type="button"
                    variant="ghost"
                  >
                    {copy.fallbackRemove}
                  </Button>
                </div>
              }
              key={`fallback-${index}`}
              title={`${copy.fallbackCustom} ${index + 1}`}
            />
          ))
        : null}

      {mode === 'custom' ? (
        <div className="py-2">
          <Button
            disabled={loading}
            onClick={() =>
              patch('fallback_providers', [...(draft.fallback_providers ?? []), { provider: '', model: '' }])
            }
            type="button"
            variant="secondary"
          >
            {copy.fallbackAdd}
          </Button>
        </div>
      ) : null}
    </SettingsContent>
  )
}
