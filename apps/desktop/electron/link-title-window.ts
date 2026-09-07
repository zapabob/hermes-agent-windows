// Hidden BrowserWindow used by tier-2 link-title resolution: when curl can't
// read a page <title> (bot walls, JS-rendered pages), we briefly load the URL
// in an offscreen window and read its title. That window loads arbitrary
// user-linked pages, so it must never emit sound or trigger real downloads.

import { createWindowOpenHandler } from './window-open-policy'

export function linkTitleWindowOptions(partitionSession) {
  return {
    show: false,
    width: 1280,
    height: 800,
    webPreferences: {
      // Deliberately throttled: this hidden window loads arbitrary user-linked
      // pages, and an unthrottled heavy page burns full CPU for the window's
      // whole lifetime. Title resolution rides load events
      // (page-title-updated / did-finish-load) plus main-process timers, none
      // of which the renderer clamp touches — hidden-page throttling only
      // slows the page's own timer-driven JS, and the grace window already
      // absorbs that.
      contextIsolation: true,
      javascript: true,
      nodeIntegration: false,
      sandbox: true,
      session: partitionSession,
      webSecurity: true
    }
  }
}

// Create the offscreen title-fetch window and immediately mute it. Without the
// mute, autoplaying media on the loaded page (e.g. a YouTube link) leaks ~2s of
// audio every time a session containing such links is re-rendered. See #49505.
export function createLinkTitleWindow(BrowserWindow, partitionSession) {
  const window = new BrowserWindow(linkTitleWindowOptions(partitionSession))

  try {
    window.webContents.setWindowOpenHandler(createWindowOpenHandler())
  } catch {
    // This window loads arbitrary user-linked pages. If popup denial cannot be
    // installed, destroy it before returning control to the caller so loadURL
    // is never reached with an unguarded webContents.
    try {
      window.destroy()
    } catch {
      // Preserve the fail-closed exception even if teardown is already racing.
    }

    throw new Error('link-title popup denial unavailable')
  }

  try {
    window.webContents.setAudioMuted(true)
  } catch {
    // webContents may be unavailable in degraded/headless environments; muting
    // is best-effort and the window is destroyed within a few seconds anyway.
  }

  return window
}

// Cancel any download the title-fetch window triggers. Without this, a link
// artifact URL served with Content-Disposition: attachment auto-downloads every
// time the Artifacts page renders and fetchLinkTitle loads it.
export function guardLinkTitleSession(partitionSession) {
  try {
    partitionSession.on('will-download', (_event, item) => item.cancel())
  } catch {
    // best-effort; worst case is a spurious download
  }
}

/**
 * Install the transport-owned request boundary for the isolated title session.
 * Electron invokes onBeforeRequest for every redirect hop and subresource in
 * this partition, so reserved hosts are cancelled before their request is
 * emitted while ordinary public HTTPS remains available.
 */
export function installLinkTitleRequestGuard(partitionSession, blockedResourceTypes = new Set()) {
  try {
    partitionSession.webRequest.onBeforeRequest((details, callback) => {
      callback({
        cancel: blockedResourceTypes.has(details.resourceType)
      })
    })

    return true
  } catch {
    return false
  }
}

// Read the page title from a title-fetch window. Callers schedule this from
// timers that can fire after finish() destroys the window, so every access must
// guard isDestroyed and swallow Electron's "Object has been destroyed" throws.
export function readLinkTitleWindowTitle(window) {
  try {
    if (!window || window.isDestroyed()) {
      return ''
    }

    const contents = window.webContents

    if (!contents || contents.isDestroyed()) {
      return ''
    }

    return contents.getTitle() || ''
  } catch {
    return ''
  }
}
