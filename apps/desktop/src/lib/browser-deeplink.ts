/**
 * Chrome / Edge → Hermes Desktop: open a web page as an in-app Browser tab.
 *
 * Official Desktop already embeds pages in an Electron webview (the Browser
 * pane). What was missing is the reverse hand-off from the user's real
 * Chrome/Edge — a `hermes://` deep link they can bookmark or share so a tab
 * lands inside Hermes instead of staying in the OS browser.
 *
 * Accepted shapes (parsed payload from Electron's deeplink handler):
 *   - hermes://open/browser?url=https%3A%2F%2Fexample.com
 *   - hermes://open/browser          (blank Browser tab / re-front)
 *
 * Only http(s) targets open in the webview. Other schemes stay out — they
 * belong to the OS (`mailto:`, `file:`, …) and must not be smuggled in.
 */

export interface BrowserOpenDeepLink {
  /** Absolute http(s) URL, or null when the link asks for a blank Browser. */
  url: string | null
}

const HTTP_RE = /^https?:$/i

function decodeMaybe(raw: string): string {
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** Normalize a candidate into an absolute http(s) URL, or null. */
export function normalizeBrowserOpenUrl(raw: string | null | undefined): string | null {
  if (raw == null) {
    return null
  }

  const trimmed = decodeMaybe(String(raw)).trim()

  if (!trimmed) {
    return null
  }

  try {
    const url = new URL(trimmed)

    if (!HTTP_RE.test(url.protocol)) {
      return null
    }

    return url.toString()
  } catch {
    return null
  }
}

/**
 * Resolve an `open/browser` deep-link payload.
 * Returns null when the payload is not the browser-open contract.
 */
export function resolveBrowserOpenDeepLink(
  payload:
    | {
        kind?: string
        name?: string
        params?: Record<string, string>
      }
    | null
    | undefined
): BrowserOpenDeepLink | null {
  if (!payload || payload.kind !== 'open') {
    return null
  }

  const name = (payload.name || '').replace(/^\//, '').toLowerCase()

  if (name !== 'browser') {
    return null
  }

  const params = payload.params || {}
  const candidate = params.url ?? params.href ?? params.u ?? ''

  if (!candidate.trim()) {
    return { url: null }
  }

  const url = normalizeBrowserOpenUrl(candidate)

  // Explicit url= that fails validation is a hard ignore (do not open blank,
  // do not navigate to /browser) so a malicious or mistyped scheme cannot
  // fall through into the generic open/ router.
  if (!url) {
    return null
  }

  return { url }
}

/** Bookmarklet / Share-target style URL for Chrome and Edge. */
export function buildBrowserOpenDeepLink(pageUrl: string, protocol = 'hermes'): string | null {
  const url = normalizeBrowserOpenUrl(pageUrl)

  if (!url) {
    return null
  }

  return `${protocol}://open/browser?url=${encodeURIComponent(url)}`
}
