import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { test } from 'vitest'

interface PackageManifest {
  overrides: Record<string, unknown>
}

interface LockEntry {
  version?: string
}

interface PackageLock {
  packages: Record<string, LockEntry>
}

test('global exact overrides cover every resolved instance, including optional dependencies', () => {
  const root = path.resolve(__dirname, '..')
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')) as PackageManifest
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8')) as PackageLock
  const mismatches: string[] = []

  for (const [name, pin] of Object.entries(manifest.overrides)) {
    // Version-qualified selectors and nested overrides intentionally have a
    // narrower scope. This contract concerns unconditional, exact root pins.
    if (typeof pin !== 'string' || !/^\d+\.\d+\.\d+$/.test(pin) || name.slice(1).includes('@')) {
      continue
    }

    for (const [entryPath, entry] of Object.entries(lock.packages)) {
      if (entryPath === `node_modules/${name}` || entryPath.endsWith(`/node_modules/${name}`)) {
        if (entry.version !== pin) {
          mismatches.push(`${entryPath}: resolved ${entry.version}, override ${pin}`)
        }
      }
    }
  }

  assert.deepEqual(mismatches, [], `Exact override drift:\n${mismatches.join('\n')}`)
})
