import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { test } from 'vitest'

interface DistributionIdentity {
  display_name: string
  version: string
}

interface DesktopManifest {
  productName: string
  version: string
  scripts: Record<string, string>
  build: {
    appId: string
    executableName: string
    nsis: { guid: string }
    win: { target: string[] }
  }
}

interface WorkspaceLock {
  packages: Record<string, { version?: string }>
}

const root = path.resolve(__dirname, '..')
const distribution = JSON.parse(fs.readFileSync(path.join(root, 'downstream/distribution.json'), 'utf8')) as DistributionIdentity
const desktop = JSON.parse(fs.readFileSync(path.join(root, 'apps/desktop/package.json'), 'utf8')) as DesktopManifest
const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8')) as WorkspaceLock

test('Desktop and its frozen workspace lock follow the downstream product version', () => {
  assert.equal(desktop.version, distribution.version)
  assert.equal(lock.packages['apps/desktop'].version, distribution.version)
})

test('Desktop retains the downstream installer identity and portable route', () => {
  assert.equal(desktop.productName, distribution.display_name)
  assert.equal(desktop.build.appId, 'io.github.zapabob.hermes-agent-windows')
  assert.equal(desktop.build.executableName, 'Hermes')
  assert.equal(desktop.build.nsis.guid, '48ae4bdc-0f8d-5252-af1e-bf7c0a8c3649')
  assert.ok(desktop.build.win.target.includes('nsis'))
  assert.ok(desktop.build.win.target.includes('zip'))
  assert.ok(desktop.scripts['dist:win:portable'].endsWith('--win zip'))
})
