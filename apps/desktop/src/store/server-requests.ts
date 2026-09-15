import type { ServerRequest } from '@hermes/shared'

/**
 * Live server→client requests keyed by request id.
 * Answers via respond() use the same socket the request arrived on.
 */
const open = new Map<string, ServerRequest>()

export function rememberServerRequest(request: ServerRequest): void {
  open.set(request.id, request)
}

export function forgetServerRequest(id: string): void {
  open.delete(id)
}

/** Answer request `id`. False when nothing is open (expired / already answered). */
export function respondToServerRequest(id: string | undefined, result: Record<string, unknown>): boolean {
  const request = id ? open.get(id) : undefined

  if (!request) {
    return false
  }

  open.delete(id!)
  request.respond(result)

  return true
}

export function hasOpenServerRequest(id: string): boolean {
  return open.has(id)
}

export function resetServerRequestsForTests(): void {
  open.clear()
}
