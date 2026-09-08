import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  createLinkTitleWindow,
  guardLinkTitleSession,
  installLinkTitleRequestGuard,
  linkTitleWindowOptions,
  readLinkTitleWindowTitle
} from './link-title-window'

function makeFakeBrowserWindow() {
  const calls = { audioMuted: [], windowOpenHandlers: [] }

  const FakeBrowserWindow = function (options) {
    this.options = options
    this.webContents = {
      setAudioMuted(value) {
        calls.audioMuted.push(value)
      },
      setWindowOpenHandler(handler) {
        calls.windowOpenHandlers.push(handler)
      }
    }
  }

  return { FakeBrowserWindow, calls }
}

test('linkTitleWindowOptions keeps the offscreen, hardened defaults', () => {
  const session = { id: 'link-titles' }
  const options = linkTitleWindowOptions(session)

  assert.equal(options.show, false)
  assert.equal(options.webPreferences.session, session)
  assert.equal(options.webPreferences.contextIsolation, true)
  assert.equal(options.webPreferences.sandbox, true)
  assert.equal(options.webPreferences.nodeIntegration, false)
})

test('createLinkTitleWindow mutes audio so historical links never autoplay sound', () => {
  // Regression for #49505: the hidden title-fetch window loaded YouTube/watch
  // URLs (to read their <title>) without muting, leaking ~2s of audio on every
  // history re-render.
  const { FakeBrowserWindow, calls } = makeFakeBrowserWindow()

  const window = createLinkTitleWindow(FakeBrowserWindow, { id: 'link-titles' })

  assert.ok(window instanceof FakeBrowserWindow)
  assert.deepEqual(calls.audioMuted, [true])
  assert.equal(calls.windowOpenHandlers.length, 1)
  assert.deepEqual(calls.windowOpenHandlers[0]({ url: 'https://attacker.test/popup' }), { action: 'deny' })
})

test('createLinkTitleWindow still returns the window if muting throws', () => {
  const windowOpenHandlers = []

  const ThrowingBrowserWindow = function (options) {
    this.options = options
    this.webContents = {
      setAudioMuted() {
        throw new Error('webContents unavailable')
      },
      setWindowOpenHandler(handler) {
        windowOpenHandlers.push(handler)
      }
    }
  }

  const window = createLinkTitleWindow(ThrowingBrowserWindow, { id: 'link-titles' })

  assert.ok(window instanceof ThrowingBrowserWindow)
  assert.equal(windowOpenHandlers.length, 1)
  assert.deepEqual(windowOpenHandlers[0]({ url: 'https://attacker.test/popup' }), { action: 'deny' })
})

test('createLinkTitleWindow destroys the window if popup denial cannot be installed', () => {
  let destroyed = false

  const ThrowingBrowserWindow = function (options) {
    this.options = options
    this.webContents = {
      setWindowOpenHandler() {
        throw new Error('handler unavailable')
      }
    }

    this.destroy = () => {
      destroyed = true
    }
  }

  assert.throws(() => createLinkTitleWindow(ThrowingBrowserWindow, { id: 'link-titles' }), /popup denial unavailable/)
  assert.equal(destroyed, true)
})

test('guardLinkTitleSession cancels downloads triggered by the title-fetch window', () => {
  let cancelled = false
  const handlers = {}
  guardLinkTitleSession({
    on: (e, h) => {
      handlers[e] = h
    }
  })
  handlers['will-download'](null, {
    cancel: () => {
      cancelled = true
    }
  })
  assert.ok(cancelled)
})

test('guardLinkTitleSession is a no-op when session.on throws', () => {
  assert.doesNotThrow(() =>
    guardLinkTitleSession({
      on() {
        throw new Error()
      }
    })
  )
})

test('title request guard allows ordinary HTTPS and preserves title reads', () => {
  let beforeRequest

  const installed = installLinkTitleRequestGuard({
    webRequest: {
      onBeforeRequest(handler) {
        beforeRequest = handler
      }
    }
  })

  let decision

  beforeRequest({ resourceType: 'mainFrame', url: 'https://example.com/docs' }, value => {
    decision = value
  })

  assert.equal(installed, true)
  assert.deepEqual(decision, { cancel: false })
  assert.equal(
    readLinkTitleWindowTitle({
      isDestroyed: () => false,
      webContents: {
        isDestroyed: () => false,
        getTitle: () => 'Example Domain'
      }
    }),
    'Example Domain'
  )
})

test.each([
  'https://x.com/owner',
  'https://sub.twitter.com./owner',
  'https://youtu.be/video',
  'wss://music.youtube.com./socket'
])('title request guard does not treat a startup-owned URL as a network policy: %s', url => {
  let beforeRequest
  assert.equal(
    installLinkTitleRequestGuard({
      webRequest: {
        onBeforeRequest(handler) {
          beforeRequest = handler
        }
      }
    }),
    true
  )
  let decision

  beforeRequest({ resourceType: 'mainFrame', url }, value => {
    decision = value
  })

  assert.deepEqual(decision, { cancel: false })
})

test('title request guard fails closed when Electron interception is unavailable', () => {
  assert.equal(
    installLinkTitleRequestGuard({
      webRequest: {
        onBeforeRequest() {
          throw new Error('unavailable')
        }
      }
    }),
    false
  )
})

test('readLinkTitleWindowTitle returns empty for missing or destroyed windows', () => {
  assert.equal(readLinkTitleWindowTitle(null), '')
  assert.equal(readLinkTitleWindowTitle(undefined), '')
  assert.equal(readLinkTitleWindowTitle({ isDestroyed: () => true }), '')
})

test('readLinkTitleWindowTitle returns empty when webContents is destroyed', () => {
  const window = {
    isDestroyed: () => false,
    webContents: { isDestroyed: () => true, getTitle: () => 'Should Not Read' }
  }

  assert.equal(readLinkTitleWindowTitle(window), '')
})

test('readLinkTitleWindowTitle swallows getTitle throws after teardown', () => {
  const window = {
    isDestroyed: () => false,
    webContents: {
      isDestroyed: () => false,
      getTitle: () => {
        throw new Error('Object has been destroyed')
      }
    }
  }

  assert.equal(readLinkTitleWindowTitle(window), '')
})

test('readLinkTitleWindowTitle returns trimmed page title', () => {
  const window = {
    isDestroyed: () => false,
    webContents: {
      isDestroyed: () => false,
      getTitle: () => 'Example Domain'
    }
  }

  assert.equal(readLinkTitleWindowTitle(window), 'Example Domain')
})
