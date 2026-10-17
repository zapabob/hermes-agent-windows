import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import { registerDeepLinkProtocol } from './protocol-registration'

const DESKTOP_ENTRY = path.resolve('owned-desktop-entry')
const ELECTRON_BINARY = path.resolve('owned-electron-binary')

interface RegistrationOptions {
  workerIndex?: string
  defaultApp?: boolean
  registrationResult?: boolean
  throwOnRegistration?: boolean
}

function runRegistration(options: RegistrationOptions = {}) {
  const calls: { protocol: string; executable?: string; args?: string[] }[] = []
  const logs: string[] = []
  let appPathReads = 0

  registerDeepLinkProtocol({
    protocol: 'hermes',
    app: {
      getAppPath: () => {
        appPathReads += 1

        return DESKTOP_ENTRY
      },
      setAsDefaultProtocolClient: (protocol, executable, args) => {
        calls.push({ protocol, executable, args })

        if (options.throwOnRegistration) {
          throw new Error('owned registration failure')
        }

        return options.registrationResult ?? true
      }
    },
    testWorkerIndex: options.workerIndex,
    defaultApp: options.defaultApp ?? false,
    execPath: ELECTRON_BINARY,
    log: message => {
      logs.push(message)
    }
  })

  return { calls, logs, appPathReads }
}

test.each(['0', ''])('test worker %j never registers a host protocol', workerIndex => {
  const result = runRegistration({ workerIndex, defaultApp: true })
  assert.equal(result.calls.length, 0)
  assert.equal(result.appPathReads, 0)
})

test('normal packaged startup retains default protocol registration', () => {
  const result = runRegistration()
  assert.deepEqual(result.calls, [{ protocol: 'hermes', executable: undefined, args: undefined }])
  assert.ok(result.logs.some(message => message.includes('registered hermes:// handler')))
})

test('development startup registers the resolved app entry', () => {
  const result = runRegistration({ defaultApp: true })
  assert.equal(result.calls.length, 1)
  assert.equal(result.calls[0].protocol, 'hermes')
  assert.equal(result.calls[0].executable, ELECTRON_BINARY)
  assert.deepEqual(result.calls[0].args, [DESKTOP_ENTRY])
})

test('a refused OS registration is not logged as successful', () => {
  const result = runRegistration({ registrationResult: false })
  assert.equal(result.calls.length, 1)
  assert.ok(result.logs.some(message => message.includes('could not register hermes:// handler')))
  assert.ok(result.logs.every(message => !message.includes('registered hermes:// handler')))
})

test('OS registration exceptions retain a diagnostic without escaping startup', () => {
  const result = runRegistration({ throwOnRegistration: true })
  assert.ok(result.logs.some(message => message.includes('owned registration failure')))
})
