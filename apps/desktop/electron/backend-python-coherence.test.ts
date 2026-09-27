import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import { createSourcePythonBackend } from './source-python'

function sourceBackend(
  root: string,
  files: string[],
  override = '',
  isWindows = true
) {
  const pathModule = isWindows ? path.win32 : path.posix
  const fileSet = new Set(files)
  const envCalls: Array<{ hermesHome: string; pythonPathEntries: string[]; venvRoot: string | null }> = []

  const backend = createSourcePythonBackend(root, 'source', ['serve'], {
    hermesHome: isWindows ? 'C:\\home' : '/home',
    isWindows,
    override,
    pathModule,
    fileExists: candidate => fileSet.has(candidate),
    getVenvSitePackagesEntries: venvRoot =>
      venvRoot ? [pathModule.join(venvRoot, isWindows ? 'Lib' : 'lib', 'site-packages')] : [],
    buildEnv: options => {
      envCalls.push(options)

      return {}
    }
  })

  return { backend, envCalls }
}

test('source without its own Python yields to the backend ladder', () => {
  for (const root of ['C:\\checkout', '/checkout']) {
    const result = sourceBackend(root, [], '', root.startsWith('C:'))
    assert.equal(result.backend, null)
    assert.deepEqual(result.envCalls, [])
  }
})

test('source prefers .venv over venv when both exist', () => {
  const root = 'C:\\checkout'
  const dotVenv = path.win32.join(root, '.venv', 'Scripts', 'python.exe')
  const plainVenv = path.win32.join(root, 'venv', 'Scripts', 'python.exe')
  const { backend, envCalls } = sourceBackend(root, [plainVenv, dotVenv])

  assert.equal(backend?.command, dotVenv)
  assert.equal(envCalls[0]?.venvRoot, path.win32.join(root, '.venv'))
  assert.deepEqual(envCalls[0]?.pythonPathEntries, [
    root,
    path.win32.join(root, '.venv', 'Lib', 'site-packages')
  ])
})

test('explicit external Python remains the command beside a checkout venv', () => {
  const root = 'C:\\checkout'
  const override = 'C:\\custom\\python.exe'
  const sourceVenv = path.win32.join(root, 'venv', 'Scripts', 'python.exe')
  const { backend, envCalls } = sourceBackend(root, [override, sourceVenv], override)

  assert.equal(backend?.command, override)
  assert.deepEqual(envCalls[0]?.pythonPathEntries, [root])
  assert.equal(envCalls[0]?.venvRoot, null)
})

test('missing override falls back only to the checkout-owned interpreter', () => {
  const root = 'C:\\checkout'
  const sourceVenv = path.win32.join(root, 'venv', 'Scripts', 'python.exe')
  const { backend, envCalls } = sourceBackend(root, [sourceVenv], 'C:\\missing\\python.exe')

  assert.equal(backend?.command, sourceVenv)
  assert.equal(envCalls[0]?.venvRoot, path.win32.join(root, 'venv'))
})

test('selected POSIX venv owns its package path', () => {
  const root = '/checkout'
  const dotVenv = path.posix.join(root, '.venv', 'bin', 'python')
  const { backend, envCalls } = sourceBackend(root, [dotVenv], '', false)

  assert.equal(backend?.command, dotVenv)
  assert.equal(envCalls[0]?.venvRoot, '/checkout/.venv')
  assert.deepEqual(envCalls[0]?.pythonPathEntries, [root, '/checkout/.venv/lib/site-packages'])
})

test('backend descriptor preserves source arguments and bootstrap choice', () => {
  const root = 'C:\\checkout'
  const interpreter = path.win32.join(root, 'venv', 'Scripts', 'python.exe')
  const { backend } = sourceBackend(root, [interpreter])

  assert.equal(backend?.kind, 'python')
  assert.equal(backend?.label, 'source')
  assert.deepEqual(backend?.args, ['-m', 'hermes_cli.main', 'serve'])
  assert.equal(backend?.root, root)
  assert.equal(backend?.bootstrap, false)
  assert.equal(backend?.shell, false)
})
