import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ModelRouteInfo } from '@/lib/chat-messages/types'

import { isModelDrift, isRouteDivergent, ModelRouteBadge } from './model-route-badge'

afterEach(() => {
  cleanup()
})

describe('ModelRouteBadge & divergence logic', () => {
  it('identifies normal routes as quiet and not divergent', () => {
    const route: ModelRouteInfo = {
      requested_provider: 'anthropic',
      requested_model: 'claude-3-7-sonnet',
      wire_provider: 'anthropic',
      wire_model: 'claude-3-7-sonnet',
      effective_provider: 'anthropic',
      effective_model: 'claude-3-7-sonnet',
      fallback: false,
      effective_model_source: 'request'
    }

    expect(isRouteDivergent(route)).toBe(false)
    expect(isModelDrift(route)).toBe(false)

    render(<ModelRouteBadge route={route} />)
    expect(screen.queryByText(/⚠ Fallback/i)).toBeNull()
    expect(screen.queryByText(/⚠ Model drift/i)).toBeNull()
    expect(screen.getByText(/3 7 Sonnet · Anthropic/i)).toBeDefined()
  })

  it('treats prefix canonicalization as normal/quiet, not drift', () => {
    const route: ModelRouteInfo = {
      requested_provider: 'anthropic',
      requested_model: 'anthropic/claude-3-7-sonnet',
      wire_provider: 'anthropic',
      wire_model: 'claude-3-7-sonnet',
      effective_provider: 'anthropic',
      effective_model: 'claude-3-7-sonnet',
      fallback: false,
      effective_model_source: 'response'
    }

    expect(isRouteDivergent(route)).toBe(false)
    expect(isModelDrift(route)).toBe(false)

    render(<ModelRouteBadge route={route} />)
    expect(screen.queryByText(/⚠ Fallback/i)).toBeNull()
    expect(screen.queryByText(/⚠ Model drift/i)).toBeNull()
  })

  it('renders prominent fallback banner when fallback occurred', () => {
    const route: ModelRouteInfo = {
      requested_provider: 'nvidia',
      requested_model: 'model-N',
      wire_provider: 'nous',
      wire_model: 'model-F',
      effective_provider: 'nous',
      effective_model: 'model-F',
      fallback: true,
      reason: 'rate limit',
      effective_model_source: 'request'
    }

    expect(isRouteDivergent(route)).toBe(true)
    expect(isModelDrift(route)).toBe(false)

    render(<ModelRouteBadge route={route} />)
    expect(screen.getByText(/⚠ Fallback:/i)).toBeDefined()
    expect(screen.getByText(/Requested: NVIDIA \/ model-N/i)).toBeDefined()
    expect(screen.getByText(/Using: Nous \/ model-F/i)).toBeDefined()
    expect(screen.getByText(/\(rate limit\)/i)).toBeDefined()
  })

  it('renders prominent model drift banner when provider reports unexpected model', () => {
    const route: ModelRouteInfo = {
      requested_provider: 'openai',
      requested_model: 'model-A',
      wire_provider: 'openai',
      wire_model: 'model-A',
      effective_provider: 'openai',
      effective_model: 'model-B',
      fallback: false,
      effective_model_source: 'response'
    }

    expect(isRouteDivergent(route)).toBe(true)
    expect(isModelDrift(route)).toBe(true)

    render(<ModelRouteBadge route={route} />)
    expect(screen.getByText(/⚠ Model drift:/i)).toBeDefined()
    expect(screen.getByText(/Requested: model-A/i)).toBeDefined()
    expect(screen.getByText(/Provider reported: model-B/i)).toBeDefined()
  })

  it('sanitizes and bounds fallback reason in badge presentation', () => {
    const route: ModelRouteInfo = {
      requested_provider: 'nvidia',
      requested_model: 'model-N',
      wire_provider: 'nous',
      wire_model: 'model-F',
      effective_provider: 'nous',
      effective_model: 'model-F',
      fallback: true,
      reason: 'Failed with Bearer token_secret_123 and sk-abcdef1234567890\n\tNew line error',
      effective_model_source: 'request'
    }

    render(<ModelRouteBadge route={route} />)
    expect(screen.getByText(/Bearer \[REDACTED\]/i)).toBeDefined()
    expect(screen.getByText(/sk-\[REDACTED\]/i)).toBeDefined()
    expect(screen.queryByText(/token_secret_123/i)).toBeNull()
    expect(screen.queryByText(/abcdef1234567890/i)).toBeNull()
  })
})
