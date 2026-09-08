import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const ts = require('typescript')
const source = fs.readFileSync(new URL('../electron/main.ts', import.meta.url), 'utf8')
const tree = ts.createSourceFile('main.ts', source, ts.ScriptTarget.Latest, true)
const compile = text => ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
function extract(name) {
  const nodes = tree.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === name)
  assert.equal(nodes.length, 1)
  return nodes[0].getText(tree)
}

test('Windows owned child survives uncertain identity and exits only after confirmation', { skip: process.platform !== 'win32', timeout: 15000 }, async () => {
  const child = spawn(process.execPath, ['-e', 'process.stdout.write("ready");setInterval(()=>{},1000)'], {
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']
  })
  const closed = once(child, 'close')
  const emergency = setTimeout(() => child.kill('SIGKILL'), 10000)
  try {
    await once(child.stdout, 'data')
    const identity = { pid: child.pid, nonce: 'synthetic-nonce', startMarker: 'synthetic-marker' }
    child.hermesBackendIdentity = identity
    let confirmed = false
    let kills = 0
    let releases = 0
    const managed = new Map([[child.pid, child]])
    const originalKill = child.kill.bind(child)
    child.kill = (...args) => { kills++; return originalKill(...args) }
    const context = vm.createContext({
      IS_WINDOWS: true, setTimeout, clearTimeout,
      process: { kill: () => { throw Error('PID-only termination forbidden') } },
      managedBackendChildren: managed,
      backendOwnership: { release: () => { releases++ } },
      rememberLog: () => {},
      processIdentityMatches: async () => child.exitCode !== null || child.signalCode !== null ? false : confirmed ? true : undefined
    })
    vm.runInContext(ts.transpileModule(extract('waitForBackendExit') + '\n' + extract('stopOwnedBackend') + '\n' + extract('releaseBackendChild'), {
      compilerOptions: { target: ts.ScriptTarget.ES2022 }
    }).outputText + '\nglobalThis.stop = stopOwnedBackend;globalThis.release = releaseBackendChild;', context)
    context.release(child)
    assert.equal(releases, 0)
    assert.equal(managed.get(child.pid), child)
    await assert.rejects(context.stop(identity), /Cannot verify ownership/)
    assert.equal(kills, 0)
    assert.equal(child.exitCode, null)
    assert.equal(child.signalCode, null)
    confirmed = true
    await context.stop(identity)
    await closed
    assert.ok(kills > 0)
    assert.ok(child.exitCode !== null || child.signalCode !== null)
    context.release(child)
    assert.equal(releases, 1)
    assert.equal(managed.has(child.pid), false)
  } finally {
    clearTimeout(emergency)
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
    await closed
  }
})

test('native ownership read failure preserves the filesystem and prevents writes', { skip: process.platform !== 'win32' }, async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-ownership-'))
  const record = path.join(directory, 'ownership.json')
  const sentinel = path.join(record, 'retained.txt')
  fs.mkdirSync(record)
  fs.writeFileSync(sentinel, 'synthetic retained evidence', 'utf8')
  let writes = 0
  const declarations = []
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'backendOwnership') declarations.push(node)
    ts.forEachChild(node, visit)
  }
  visit(tree)
  assert.equal(declarations.length, 1)
  const context = vm.createContext({
    exports: {}, fs, DESKTOP_BACKEND_OWNERSHIP_PATH: record,
    backendIdentityMatches: async () => true, backendParentMatches: async () => true,
    stopOwnedBackend: () => { throw Error('Unexpected stop') }, rememberLog: () => {},
    writeBackendOwnership: value => { writes++; fs.writeFileSync(record, value, 'utf8') }
  })
  try {
    const ownershipSource = fs.readFileSync(new URL('../electron/backend-ownership.ts', import.meta.url), 'utf8')
    vm.runInContext(compile(ownershipSource), context)
    context.createBackendOwnership = context.exports.createBackendOwnership
    vm.runInContext('globalThis.owner = ' + declarations[0].initializer.getText(tree), context)
    await assert.rejects(context.owner.reapOrphans())
    assert.equal(writes, 0)
    assert.equal(fs.readFileSync(sentinel, 'utf8'), 'synthetic retained evidence')
    fs.unlinkSync(sentinel)
    fs.rmdirSync(record)
    await context.owner.reapOrphans()
    assert.equal(writes, 1)
    assert.deepEqual(JSON.parse(fs.readFileSync(record, 'utf8')).backends, [])
  } finally {
    if (fs.existsSync(sentinel)) fs.unlinkSync(sentinel)
    if (fs.existsSync(record)) {
      if (fs.statSync(record).isDirectory()) fs.rmdirSync(record)
      else fs.unlinkSync(record)
    }
    fs.rmdirSync(directory)
  }
})
