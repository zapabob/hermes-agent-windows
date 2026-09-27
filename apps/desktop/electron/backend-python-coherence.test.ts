import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { runInNewContext } from 'node:vm'

import { ScriptTarget, transpileModule } from 'typescript'
import { test } from 'vitest'

// ── Regression guard: backend interpreter / site-packages coherence ─────────
//
// Live repro (2026-08-23, macOS dev run): the checkout had BOTH venvs —
//   .venv/  → Python 3.12 (dev tooling)
//   venv/   → Python 3.11 (the CLI install venv, owns the real deps)
//
// findPythonForRoot() prefers `.venv/bin/python` (3.12), but
// createPythonBackend() hardcodes `venvRoot = path.join(root, 'venv')` and
// puts venv/lib/python3.11/site-packages on PYTHONPATH. The 3.12 interpreter
// then imports 3.11-compiled native wheels and dies on the FIRST import:
//   ImportError: No module named 'pydantic_core._pydantic_core'
// → backend exits(1) before ready → "Gateway offline" → renderer falls back
// to a dead 127.0.0.1:9119 and every profile fails to activate.
//
// The invariant these tests pin down: the venv whose interpreter is selected
// and the venv whose site-packages go on PYTHONPATH must be THE SAME venv.
// One resolver must own that decision (AGENTS.md "observable ladder" rule 6).

const here = path.dirname(fileURLToPath(import.meta.url))
const mainTsSource = fs.readFileSync(path.join(here, 'main.ts'), 'utf8')

function extractFunction(source: string, name: string): string {
  const start = source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `function ${name} not found in main.ts`)

  // Slice to the next top-level `function ` declaration — crude but stable
  // for the flat function layout main.ts uses.
  const rest = source.slice(start)
  const next = rest.slice(1).search(/\nfunction /)

  return next === -1 ? rest : rest.slice(0, next + 1)
}

function runSourcePythonFinder(root: string, isWindows: boolean, files: string[], override = '') {
  let systemLookupCalls = 0
  const fileSet = new Set(files)

  const finder = runInNewContext(
    `${extractFunction(mainTsSource, 'findPythonForRoot')}\nfindPythonForRoot`,
    {
      IS_WINDOWS: isWindows,
      fileExists: (candidate: string) => fileSet.has(candidate),
      findSystemPython: () => {
        systemLookupCalls += 1

        return isWindows ? 'C:\\Python312\\python.exe' : '/usr/bin/python3'
      },
      path: isWindows ? path.win32 : path.posix,
      process: { env: { HERMES_DESKTOP_PYTHON: override } }
    }
  ) as (sourceRoot: string) => string | null

  return { python: finder(root), systemLookupCalls }
}

test('a source checkout with no own venv does not select PATH Python', () => {
  for (const [root, isWindows] of [['C:\\checkout', true], ['/checkout', false]] as const) {
    const resolved = runSourcePythonFinder(root, isWindows, [])
    assert.equal(resolved.python, null)
    assert.equal(resolved.systemLookupCalls, 0)
  }
})

test('source interpreter selection keeps explicit override and .venv preference', () => {
  const root = 'C:\\checkout'
  const dotVenv = path.win32.join(root, '.venv', 'Scripts', 'python.exe')
  const plainVenv = path.win32.join(root, 'venv', 'Scripts', 'python.exe')
  const override = 'C:\\custom\\python.exe'

  assert.deepEqual(runSourcePythonFinder(root, true, [plainVenv, dotVenv]), {
    python: dotVenv,
    systemLookupCalls: 0
  })
  assert.deepEqual(runSourcePythonFinder(root, true, [plainVenv, dotVenv, override], override), {
    python: override,
    systemLookupCalls: 0
  })
})

function runSourceBackend(root: string, files: string[], override: string) {
  const source = ['findPythonForRoot', 'getVenvPython', 'venvRootForPython', 'createPythonBackend']
    .map(name => extractFunction(mainTsSource, name))
    .join('\n')

  const compiled = transpileModule(source, { compilerOptions: { target: ScriptTarget.ES2022 } }).outputText
  const fileSet = new Set(files)

  const create = runInNewContext(`${compiled}\ncreatePythonBackend`, {
    HERMES_HOME: 'C:\\home',
    IS_WINDOWS: true,
    buildDesktopBackendEnv: (options: { pythonPathEntries: string[]; venvRoot: null | string }) => options,
    fileExists: (candidate: string) => fileSet.has(candidate),
    findSystemPython: () => 'C:\\Python312\\python.exe',
    getVenvSitePackagesEntries: (venvRoot: null | string) =>
      venvRoot ? [path.win32.join(venvRoot, 'Lib', 'site-packages')] : [],
    path: path.win32,
    process: { env: { HERMES_DESKTOP_PYTHON: override } }
  }) as (sourceRoot: string, label: string, args: string[]) => null | {
    command: string
    env: { pythonPathEntries: string[]; venvRoot: null | string }
  }

  return create(root, 'source', ['serve'])
}

test('an explicit external Python remains the backend command even when the checkout has a venv', () => {
  const root = 'C:\\checkout'
  const override = 'C:\\custom\\python.exe'
  const sourceVenv = path.win32.join(root, 'venv', 'Scripts', 'python.exe')
  const backend = runSourceBackend(root, [override, sourceVenv], override)

  assert.equal(backend?.command, override)
  assert.equal(backend?.env.venvRoot, null)
  assert.equal(backend?.env.pythonPathEntries.length, 1)
  assert.equal(backend?.env.pythonPathEntries[0], root)
})

test('a selected checkout venv still owns its backend command and Python path', () => {
  const root = 'C:\\checkout'
  const dotVenvRoot = path.win32.join(root, '.venv')
  const dotVenv = path.win32.join(dotVenvRoot, 'Scripts', 'python.exe')
  const backend = runSourceBackend(root, [dotVenv], '')

  assert.equal(backend?.command, dotVenv)
  assert.equal(backend?.env.venvRoot, dotVenvRoot)
  assert.equal(backend?.env.pythonPathEntries.length, 2)
})

test('findPythonForRoot preference order includes .venv before venv (context for the coherence tests)', () => {
  const fn = extractFunction(mainTsSource, 'findPythonForRoot')
  const venvIdx = fn.indexOf("'.venv'")
  const plainIdx = fn.indexOf("'venv'")

  assert.notEqual(venvIdx, -1, 'expected findPythonForRoot to probe .venv')
  assert.notEqual(plainIdx, -1, 'expected findPythonForRoot to probe venv')
  assert.ok(
    venvIdx < plainIdx,
    '.venv is probed before venv — this ordering is what the hardcoded venvRoot below disagrees with'
  )
})

// Fixed: createPythonBackend derives venvRoot from the selected interpreter
// via venvRootForPython(python, root), falling back to root/venv only for a
// system python. This test guards against re-hardcoding the venv path.
test('createPythonBackend derives venvRoot from the selected interpreter, not a hardcoded venv path', () => {
  const fn = extractFunction(mainTsSource, 'createPythonBackend')

  // The buggy shape: interpreter picked by findPythonForRoot (may be .venv),
  // while venvRoot/PYTHONPATH is unconditionally root/venv.
  const hardcodesVenv = /venvRoot\s*=\s*path\.join\(root,\s*'venv'\)/.test(fn)
  const derivesFromPython = /findPythonForRoot|python/.test(fn) && !hardcodesVenv

  assert.ok(
    derivesFromPython,
    'createPythonBackend hardcodes venvRoot=path.join(root, "venv") while findPythonForRoot may select .venv/bin/python — ' +
      'a root with both venvs gets a 3.12 interpreter with 3.11 site-packages on PYTHONPATH and crashes on the first native import'
  )
})

// Pure-logic mirror of the same invariant, testable without main.ts exports:
// given a root where BOTH .venv and venv exist, whatever venv the interpreter
// came from must be the venv used for site-packages. This encodes the fix's
// contract so the implementation can be extracted against it later.
export function coherentVenvRootForPython(pythonPath: string, root: string): string | null {
  // The venv root is the directory two levels up from <venv>/bin/python
  // (Scripts/python.exe on Windows). A system interpreter (outside `root`)
  // is NOT a venv — pairing it with any venv's site-packages needs the same
  // version check, so it returns null here.
  const posix = pythonPath.match(/^(.*)\/bin\/python[0-9.]*$/)
  const win = pythonPath.match(/^(.*)[\\/]Scripts[\\/]python\.exe$/i)
  const candidate = posix?.[1] ?? win?.[1] ?? null

  if (!candidate) {
    return null
  }

  const normalizedRoot = root.replace(/\\/g, '/').replace(/\/+$/, '')
  const normalizedCandidate = candidate.replace(/\\/g, '/')

  return normalizedCandidate.startsWith(`${normalizedRoot}/`) ? candidate : null
}

test('coherentVenvRootForPython maps a selected interpreter back to ITS venv root', () => {
  assert.equal(coherentVenvRootForPython('/repo/.venv/bin/python', '/repo'), '/repo/.venv')
  assert.equal(coherentVenvRootForPython('/repo/venv/bin/python', '/repo'), '/repo/venv')
  assert.equal(coherentVenvRootForPython('C:\\repo\\venv\\Scripts\\python.exe', 'C:\\repo'), 'C:\\repo\\venv')
  assert.equal(coherentVenvRootForPython('/usr/bin/python3', '/repo'), null)
})

test('dual-venv root: site-packages must come from the venv that owns the selected interpreter', () => {
  // Simulates the live repro: interpreter resolved to .venv (3.12), so the
  // ONLY coherent venvRoot for PYTHONPATH is .venv — never the sibling venv.
  const selected = '/repo/.venv/bin/python'
  const venvRoot = coherentVenvRootForPython(selected, '/repo')

  assert.equal(venvRoot, '/repo/.venv')
  assert.notEqual(
    venvRoot,
    '/repo/venv',
    'pairing a .venv interpreter with venv/ site-packages is the crash from the live repro'
  )
})
