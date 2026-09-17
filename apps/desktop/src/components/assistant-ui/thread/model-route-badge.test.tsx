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

  it('redacts Basic auth and github_pat tokens from fallback reasons', () => {
    const route: ModelRouteInfo = {
      requested_provider: 'nvidia',
      requested_model: 'model-N',
      wire_provider: 'nous',
      wire_model: 'model-F',
      effective_provider: 'nous',
      effective_model: 'model-F',
      fallback: true,
      reason: 'HTTP 401 Basic dXNlcjpwYXNz and Authorization: token secret12345 github_pat_11AAAAAA00000000000000_1234567890abcdef',
      effective_model_source: 'request'
    }

    render(<ModelRouteBadge route={route} />)
    expect(screen.getByText(/Basic \[REDACTED\]/i)).toBeDefined()
    expect(screen.getByText(/Authorization: \[REDACTED\]/i)).toBeDefined()
    expect(screen.getByText(/github_pat_\[REDACTED\]/i)).toBeDefined()
    expect(screen.queryByText(/dXNlcjpwYXNz/i)).toBeNull()
    expect(screen.queryByText(/secret12345/i)).toBeNull()
    expect(screen.queryByText(/11AAAAAA00000000000000/i)).toBeNull()
  })

  it('suppresses drift for Copilot ACP default but reports drift for custom provider with auto', () => {
    const copilotRoute: ModelRouteInfo = {
      requested_provider: 'copilot-acp',
      requested_model: 'default',
      wire_provider: 'copilot-acp',
      wire_model: 'default',
      effective_provider: 'copilot-acp',
      effective_model: 'claude-3-5-sonnet',
      fallback: false,
      effective_model_source: 'server'
    }

    expect(isModelDrift(copilotRoute)).toBe(false)
    expect(isRouteDivergent(copilotRoute)).toBe(false)

    const openaiAutoRoute: ModelRouteInfo = {
      requested_provider: 'openai',
      requested_model: 'auto',
      wire_provider: 'openai',
      wire_model: 'auto',
      effective_provider: 'openai',
      effective_model: 'gpt-4o',
      fallback: false,
      effective_model_source: 'server'
    }

    expect(isModelDrift(openaiAutoRoute)).toBe(true)
    expect(isRouteDivergent(openaiAutoRoute)).toBe(true)
  })

  it('reports drift for custom provider with requested_model=auto and server-reported effective_model', () => {
    const customRoute: ModelRouteInfo = {
      requested_provider: 'custom',
      requested_model: 'auto',
      wire_provider: 'custom',
      wire_model: 'auto',
      effective_provider: 'custom',
      effective_model: 'another-model',
      fallback: false,
      effective_model_source: 'server'
    }

    expect(isModelDrift(customRoute)).toBe(true)
    expect(isRouteDivergent(customRoute)).toBe(true)
  })

  it('verifies session route isolation: Session B never renders Session A fallback route', () => {
    const sessionARoute: ModelRouteInfo = {
      sessionId: 'session-A',
      requested_provider: 'nvidia',
      requested_model: 'deepseek-r1',
      wire_provider: 'nous',
      wire_model: 'hermes-3-70b',
      effective_provider: 'nous',
      effective_model: 'hermes-3-70b',
      fallback: true,
      reason: 'HTTP 429 rate limit'
    }

    const sessionBRoute: ModelRouteInfo = {
      sessionId: 'session-B',
      requested_provider: 'openai',
      requested_model: 'gpt-4o',
      wire_provider: 'openai',
      wire_model: 'gpt-4o',
      effective_provider: 'openai',
      effective_model: 'gpt-4o',
      fallback: false
    }

    // Render Session B
    const { container: containerB } = render(<ModelRouteBadge route={sessionBRoute} />)
    expect(isRouteDivergent(sessionBRoute)).toBe(false)
    expect(containerB.querySelector('[data-slot="aui_route-fallback-badge"]')).toBeNull()
    expect(screen.queryByText(/HTTP 429 rate limit/i)).toBeNull()
    expect(screen.queryByText(/deepseek-r1/i)).toBeNull()
    expect(screen.queryByText(/hermes-3-70b/i)).toBeNull()

    // Render Session A
    const { container: containerA } = render(<ModelRouteBadge route={sessionARoute} />)
    expect(isRouteDivergent(sessionARoute)).toBe(true)
    expect(containerA.querySelector('[data-slot="aui_route-fallback-badge"]')).not.toBeNull()
    expect(screen.getByText(/HTTP 429 rate limit/i)).toBeDefined()
  })
})
