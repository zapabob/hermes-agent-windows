/**
 * W05: single place to resolve browser connection/profile/session binding.
 * REST and WS callers must share this shape so a late response cannot land on
 * the wrong profile after a switch.
 */
export interface BrowserSurfaceBinding {
  profile: string
  storedSessionId: string
  logicalSessionId: string
  generation: string
}

export interface BindBrowserSurfaceInput {
  profile: string
  storedSessionId: string
  logicalSessionId: string
  generation: string
}

export function bindBrowserSurface(input: BindBrowserSurfaceInput): BrowserSurfaceBinding {
  const profile = input.profile.trim()
  if (!profile) {
    throw new Error('browser surface binding requires a non-empty profile')
  }
  if (!input.storedSessionId || !input.logicalSessionId || !input.generation) {
    throw new Error('browser surface binding requires stored, logical, and generation ids')
  }
  return {
    profile,
    storedSessionId: input.storedSessionId,
    logicalSessionId: input.logicalSessionId,
    generation: input.generation,
  }
}

/** True when *candidate* must not be applied to the live binding. */
export function rejectStaleProfileResponse(
  live: BrowserSurfaceBinding,
  candidate: BrowserSurfaceBinding,
): boolean {
  return (
    live.profile !== candidate.profile
    || live.generation !== candidate.generation
    || live.storedSessionId !== candidate.storedSessionId
  )
}
