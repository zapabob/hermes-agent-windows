import type { FC } from 'react'

import type { ModelRouteInfo } from '@/lib/chat-messages/types'
import { displayModelName } from '@/lib/model-status-label'
import { cn } from '@/lib/utils'

export function isModelDrift(route?: ModelRouteInfo | null): boolean {
  if (!route || route.fallback) {return false}

  if (route.isDrift !== undefined) {return route.isDrift}

  if (route.is_drift !== undefined) {return route.is_drift}

  const src = route.effectiveModelSource || route.effective_model_source

  if (src !== 'response' && src !== 'server') {return false}

  const req = (route.requestedModel || route.requested_model || '').trim()
  const wire = (route.wireModel || route.wire_model || '').trim()
  const eff = (route.effectiveModel || route.effective_model || '').trim()

  if (!eff || !req) {return false}

  const reqClean = (req.includes('/') ? req.slice(req.lastIndexOf('/') + 1) : req).toLowerCase()
  const wireClean = (wire.includes('/') ? wire.slice(wire.lastIndexOf('/') + 1) : wire).toLowerCase()
  const effClean = (eff.includes('/') ? eff.slice(eff.lastIndexOf('/') + 1) : eff).toLowerCase()

  if (effClean === reqClean || effClean === wireClean) {return false}

  const reqProv = (route.requestedProvider || route.requested_provider || '').trim().toLowerCase()
  const wireProv = (route.wireProvider || route.wire_provider || '').trim().toLowerCase()
  const effProv = (route.effectiveProvider || route.effective_provider || '').trim().toLowerCase()

  const isCopilot =
    reqProv === 'copilot' ||
    reqProv === 'copilot-acp' ||
    wireProv === 'copilot' ||
    wireProv === 'copilot-acp' ||
    effProv === 'copilot' ||
    effProv === 'copilot-acp'

  if (isCopilot && (
    reqClean === 'copilot-acp' || reqClean === 'default' || reqClean === 'auto' ||
    wireClean === 'copilot-acp' || wireClean === 'default' || wireClean === 'auto'
  )) {
    return false
  }

  return true
}

export function isRouteDivergent(route?: ModelRouteInfo | null): boolean {
  if (!route) {return false}

  if (route.isDivergent !== undefined) {return route.isDivergent}

  if (route.is_divergent !== undefined) {return route.is_divergent}

  if (route.fallback) {return true}

  return isModelDrift(route)
}

function prettifyProvider(provider?: string): string {
  const p = (provider || '').trim()

  if (!p) {return ''}

  const mapping: Record<string, string> = {
    openai: 'OpenAI',
    openrouter: 'OpenRouter',
    anthropic: 'Anthropic',
    google: 'Google',
    gemini: 'Google',
    deepseek: 'DeepSeek',
    copilot: 'Copilot',
    'copilot-acp': 'Copilot ACP',
    nvidia: 'NVIDIA',
    meta: 'Meta',
    ollama: 'Ollama'
  }

  return mapping[p.toLowerCase()] || (p.charAt(0).toUpperCase() + p.slice(1))
}

interface ModelRouteBadgeProps {
  route?: ModelRouteInfo | null
  className?: string
}

export function sanitizeAndBoundRouteReason(
  reason?: null | string,
  maxLen = 200
): null | string {
  if (!reason) {
    return null
  }

  let cleaned = String(reason)

  // eslint-disable-next-line no-control-regex -- normalize ANSI escape sequences
  cleaned = cleaned.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '')
  cleaned = cleaned.replace(/\bAuthorization\s*:\s*[A-Za-z0-9_-]+\s+[^\s\r\n]+/gi, 'Authorization: [REDACTED]')
  cleaned = cleaned.replace(/\b(Bearer|Basic)\s+[A-Za-z0-9_\-.=]+/gi, '$1 [REDACTED]')
  cleaned = cleaned.replace(/\bsk-[a-zA-Z0-9_\-.]{8,}\b/g, 'sk-[REDACTED]')
  cleaned = cleaned.replace(/\bgh[pousr]_[a-zA-Z0-9]{16,}\b/g, 'gh*_[REDACTED]')
  cleaned = cleaned.replace(/\bgithub_pat_[a-zA-Z0-9_]{20,}\b/gi, 'github_pat_[REDACTED]')
  cleaned = cleaned.replace(/\bAIza[0-9A-Za-z-_]{35}\b/g, 'AIza[REDACTED]')
  cleaned = cleaned.replace(
    /\b(api[-_]?key|token|secret|password|authorization)\s*[:=]\s*['"]?([a-zA-Z0-9_\-.]{8,})['"]?/gi,
    '$1=[REDACTED]'
  )
  // eslint-disable-next-line no-control-regex -- strip control characters
  cleaned = cleaned.replace(/[\x00-\x1f\x7f-\x9f]/g, ' ')
  cleaned = cleaned.replace(/\s+/g, ' ').trim()

  if (!cleaned) {
    return null
  }

  if (cleaned.length > maxLen) {
    return `${cleaned.slice(0, maxLen - 3).trimEnd()}...`
  }

  return cleaned
}

export const ModelRouteBadge: FC<ModelRouteBadgeProps> = ({ route, className }) => {
  if (!route) {
    return null
  }

  const isFallback = Boolean(route.fallback)
  const isDrift = isModelDrift(route)
  const reqModel = route.requestedModel || route.requested_model || ''
  const reqProvider = prettifyProvider(route.requestedProvider || route.requested_provider)
  const effModel = route.effectiveModel || route.effective_model || ''
  const effProvider = prettifyProvider(route.effectiveProvider || route.effective_provider)
  const reason = sanitizeAndBoundRouteReason(route.reason)

  if (isFallback) {
    return (
      <div
        className={cn(
          'flex flex-wrap items-center gap-1 rounded-md border border-amber-500/35 bg-amber-500/10 px-2 py-0.5 text-[0.6875rem] font-medium text-amber-700 dark:text-amber-300',
          className
        )}
        data-slot="aui_route-fallback-badge"
        title={reason ? `Fallback: ${reason}` : 'Fallback active'}
      >
        <span className="font-semibold text-amber-600 dark:text-amber-400">⚠ Fallback:</span>
        <span>
          Requested: {reqProvider ? `${reqProvider} / ` : ''}
          {reqModel}
        </span>
        <span className="text-muted-foreground/60">→</span>
        <span>
          Using: {effProvider ? `${effProvider} / ` : ''}
          {effModel}
        </span>
        {reason && <span className="opacity-80">({reason})</span>}
      </div>
    )
  }

  if (isDrift) {
    return (
      <div
        className={cn(
          'flex flex-wrap items-center gap-1 rounded-md border border-amber-500/35 bg-amber-500/10 px-2 py-0.5 text-[0.6875rem] font-medium text-amber-700 dark:text-amber-300',
          className
        )}
        data-slot="aui_route-drift-badge"
        title="Provider reported a different model than requested"
      >
        <span className="font-semibold text-amber-600 dark:text-amber-400">⚠ Model drift:</span>
        <span>Requested: {reqModel}</span>
        <span className="text-muted-foreground/60">|</span>
        <span>Provider reported: {effModel}</span>
      </div>
    )
  }

  // Normal / Canonicalization only: Quiet label, no alert
  const quietLabel = route.quietLabel || route.quiet_label || `${displayModelName(effModel)} · ${effProvider}`

  return (
    <span
      className={cn('select-none text-[0.6875rem] leading-5 text-muted-foreground/60', className)}
      data-slot="aui_route-quiet-label"
      title={`Route: ${effModel} (${effProvider})`}
    >
      {quietLabel}
    </span>
  )
}
