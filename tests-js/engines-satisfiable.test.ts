import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

import { test } from 'vitest'

interface SemverLibrary {
  minVersion: (range: string) => { version: string } | null
  satisfies: (version: string, range: string) => boolean
  validRange: (range: string) => string | null
}

interface EngineManifest {
  engines: { node: string; npm?: string }
  dependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

interface EngineLock {
  packages: Record<string, { engines?: Record<string, string> }>
}

const require = createRequire(import.meta.url)
const semver = require('semver') as SemverLibrary
const root = path.resolve(__dirname, '..')
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')) as EngineManifest
const desktop = JSON.parse(fs.readFileSync(path.join(root, 'apps/desktop/package.json'), 'utf8')) as EngineManifest
const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8')) as EngineLock

test('the executing Node runtime satisfies root and Desktop engine declarations', () => {
  assert.ok(semver.validRange(manifest.engines.node))
  assert.ok(semver.validRange(desktop.engines.node))
  assert.ok(semver.satisfies(process.versions.node, manifest.engines.node))
  assert.ok(semver.satisfies(process.versions.node, desktop.engines.node))
})

test('the actual npm invoking workspace checks satisfies the declared npm range', () => {
  const npmCli = process.env.npm_execpath

  assert.ok(npmCli, 'Run workspace checks through the package scripts so npm is observable')
  assert.ok(manifest.engines.npm)

  const version = execFileSync(process.execPath, [npmCli, '--version'], {
    encoding: 'utf8',
    timeout: 30_000,
    windowsHide: true
  }).trim()

  assert.ok(semver.satisfies(version, manifest.engines.npm), `${version} does not satisfy ${manifest.engines.npm}`)
})

test('each declared Node minimum can run Desktop and its resolved toolchain', () => {
  const dependencies = { ...desktop.dependencies, ...desktop.devDependencies }

  for (const alternative of manifest.engines.node.split('||')) {
    const minimum = semver.minVersion(alternative.trim())

    assert.ok(minimum, `Unsatisfiable Node alternative: ${alternative}`)
    assert.ok(semver.satisfies(minimum.version, desktop.engines.node))

    for (const name of Object.keys(dependencies)) {
      const entry = lock.packages[`apps/desktop/node_modules/${name}`] ?? lock.packages[`node_modules/${name}`]
      const requirement = entry?.engines?.node

      assert.ok(entry, `Missing resolved Desktop dependency: ${name}`)

      if (requirement) {
        assert.ok(semver.satisfies(minimum.version, requirement), `${name} needs ${requirement}, beyond declared ${minimum.version}`)
      }
    }
  }
})

test.each(['11.10.0', '11.12.1', '11.16.0'])('npm %s with broken release-age exclusions is rejected', version => {
  assert.ok(manifest.engines.npm)
  assert.equal(semver.satisfies(version, manifest.engines.npm), false)
})

test('frozen engine metadata mirrors the manifests', () => {
  assert.deepEqual(lock.packages[''].engines, manifest.engines)
  assert.deepEqual(lock.packages['apps/desktop'].engines, desktop.engines)
})
