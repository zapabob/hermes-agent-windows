import { describe, expect, it } from 'vitest'

import { buildBrowserOpenDeepLink, normalizeBrowserOpenUrl, resolveBrowserOpenDeepLink } from './browser-deeplink'
import { resolveDeepLinkAction } from './deeplink-routes'

describe('browser-deeplink', () => {
  it('accepts absolute http(s) URLs and rejects other schemes', () => {
    expect(normalizeBrowserOpenUrl('https://example.com/a')).toBe('https://example.com/a')
    expect(normalizeBrowserOpenUrl('http://localhost:5173/')).toBe('http://localhost:5173/')
    expect(normalizeBrowserOpenUrl('javascript:alert(1)')).toBeNull()
    expect(normalizeBrowserOpenUrl('file:///C:/Secrets.txt')).toBeNull()
    expect(normalizeBrowserOpenUrl('hermes://open/settings')).toBeNull()
  })

  it('resolves hermes://open/browser?url=… into an open-browser action', () => {
    const action = resolveDeepLinkAction({
      kind: 'open',
      name: 'browser',
      params: { url: 'https://news.ycombinator.com/' }
    })

    expect(action).toEqual({ type: 'open-browser', url: 'https://news.ycombinator.com/' })
  })

  it('opens a blank Browser when url is omitted', () => {
    expect(resolveBrowserOpenDeepLink({ kind: 'open', name: 'browser', params: {} })).toEqual({
      url: null
    })
    expect(resolveDeepLinkAction({ kind: 'open', name: 'browser', params: {} })).toEqual({
      type: 'open-browser',
      url: null
    })
  })

  it('ignores open/browser with a non-http url instead of navigating to /browser', () => {
    expect(
      resolveDeepLinkAction({
        kind: 'open',
        name: 'browser',
        params: { url: 'javascript:alert(1)' }
      })
    ).toEqual({ type: 'handled' })
  })

  it('builds a Chrome/Edge-handable deep link', () => {
    expect(buildBrowserOpenDeepLink('https://example.com/x?y=1')).toBe(
      'hermes://open/browser?url=https%3A%2F%2Fexample.com%2Fx%3Fy%3D1'
    )
    expect(buildBrowserOpenDeepLink('javascript:alert(1)')).toBeNull()
  })
})
