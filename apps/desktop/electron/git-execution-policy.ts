// The Python subprocess compatibility owner defines Git policy. This module
// only transports its result through a main-owned interpreter, without a backend.
import { execFile, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { GitError } from 'simple-git'

export interface GitPolicyRuntime {
  command: string
  argsPrefix: string[]
  ownerRoot: string
}

export class GitPolicyError extends GitError {
  readonly code = 'HERMES_GIT_POLICY_REFUSED'
  constructor(message: string) {
    super(undefined, message)
  }
}

export function rethrowGitPolicyError(error: unknown): void {
  if (error instanceof GitPolicyError) throw error
}

let resolveRuntime: (() => GitPolicyRuntime | null) | null = null
let resolveGit: (() => string) | null = null

export function configureGitPolicyRuntime(runtime: () => GitPolicyRuntime | null, git: () => string): void {
  resolveRuntime = runtime
  resolveGit = git
}

const policyProgram = String.raw`
import importlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
git=sys.argv[2]
cwd=sys.argv[3]
args=json.loads(sys.argv[4])
sys.path.insert(0,str(root))
owner=importlib.import_module('hermes_cli._subprocess_compat')
expected=(root/'hermes_cli'/'_subprocess_compat.py').resolve()
if pathlib.Path(owner.__file__).resolve()!=expected:
    raise RuntimeError('Git policy owner mismatch')
argv=owner.harden_git_argv(args)
env=owner.noninteractive_repo_git_env(cwd,git_bin=git,preserve_eol=True)
if env is None:
    raise RuntimeError(owner.FILTER_DISCOVERY_FAILED)
# Both preflight and final execution validate through the same Python owner.
if not owner.git_policy_environment_valid(env):
    raise RuntimeError('Incomplete static Git environment')
names={'GIT_TERMINAL_PROMPT','GCM_INTERACTIVE','GIT_CONFIG_GLOBAL','GIT_CONFIG_SYSTEM',
       'GIT_CONFIG_NOSYSTEM','GIT_PAGER','PAGER','GIT_EDITOR','GIT_CONFIG_COUNT'}
safe={k:v for k,v in env.items() if k in names or k.startswith(('GIT_CONFIG_KEY_','GIT_CONFIG_VALUE_'))}
sys.stdout.write(json.dumps({'owner':str(expected),'interpreter':sys.executable,'git':git,
                            'environment':safe,'argv':argv,'diffFlags':list(owner.NO_DRIVER_DIFF_FLAGS)}))
`

interface GitPolicyRuntimeSnapshot {
  readonly command: string
  readonly argsPrefix: readonly string[]
  readonly ownerRoot: string
}

interface PolicyResult {
  git: string
  environment: Record<string, string>
  argv: string[]
  diffFlags: string[]
  readonly runtime: GitPolicyRuntimeSnapshot
}

function samePath(left: string, right: string): boolean {
  const normalize = (value: string) => {
    const result = fs.realpathSync(value)
    return process.platform === 'win32' ? result.toLowerCase() : result
  }
  return normalize(left) === normalize(right)
}

function gitExecutionAuthority(selectedGit?: string) {
  let runtime: GitPolicyRuntimeSnapshot | null = null
  let git: string | undefined
  try {
    const selected = resolveRuntime?.()
    if (selected) {
      // Copy before asynchronous discovery; the resolver's object may change.
      runtime = Object.freeze({command: selected.command, ownerRoot: selected.ownerRoot,
        argsPrefix: Object.freeze([...selected.argsPrefix])})
    }
    git = selectedGit || resolveGit?.()
  } catch {
    throw new GitPolicyError('Trusted Git policy runtime resolution failed.')
  }
  if (!runtime || !git || !path.isAbsolute(git) || !path.isAbsolute(runtime.command) ||
      !path.isAbsolute(runtime.ownerRoot) || runtime.argsPrefix.length !== 0) {
    throw new GitPolicyError('Trusted Git policy runtime is unavailable.')
  }
  const owner = path.join(runtime.ownerRoot, 'hermes_cli', '_subprocess_compat.py')
  if (!fs.existsSync(owner) || !fs.existsSync(runtime.command) || !fs.existsSync(git)) {
    throw new GitPolicyError('Trusted Git policy files are unavailable.')
  }
  return {git, runtime, owner}
}

export async function gitExecutionPolicy(cwd: string, selectedGit?: string, args: string[] = []): Promise<PolicyResult> {
  const {git, runtime, owner} = gitExecutionAuthority(selectedGit)
  return new Promise<PolicyResult>((resolve, reject) => {
    const child = execFile(runtime.command, ['-I', '-B', '-c', policyProgram, runtime.ownerRoot,
      git, cwd, JSON.stringify(args)], {cwd: runtime.ownerRoot, windowsHide: true,
      timeout: 120_000, maxBuffer: 512 * 1024, encoding: 'utf8'}, (error, stdout) => {
      if (error) {
        reject(new GitPolicyError('Repository Git policy discovery refused the operation.'))
        return
      }
      try {
        const result = JSON.parse(stdout)
        if (!samePath(result.owner, owner) || !samePath(result.interpreter, runtime.command) ||
            result.git !== git || !Array.isArray(result.argv) || !result.argv.every((value: unknown) => typeof value === 'string') ||
            !Array.isArray(result.diffFlags) || result.diffFlags.join(',') !== '--no-ext-diff,--no-textconv' ||
            !result.environment || typeof result.environment !== 'object') {
          throw new Error('Invalid Git policy authority')
        }
        const entries = Object.entries(result.environment)
        if (entries.length > 1100 || entries.some(([key, value]) =>
          !/^(?:GIT_(?:TERMINAL_PROMPT|PAGER|EDITOR|CONFIG_(?:GLOBAL|SYSTEM|NOSYSTEM|COUNT|KEY_\d+|VALUE_\d+))|GCM_INTERACTIVE|PAGER)$/.test(key) ||
          typeof value !== 'string' || value.length > 8192)) throw new Error('Invalid policy environment')
        const count = Number(result.environment.GIT_CONFIG_COUNT)
        if (!Number.isInteger(count) || count < 1 || count > 1000) throw new Error('Invalid configuration count')
        for (let index = 0; index < count; index++) {
          if (typeof result.environment[`GIT_CONFIG_KEY_${index}`] !== 'string' ||
              typeof result.environment[`GIT_CONFIG_VALUE_${index}`] !== 'string') throw new Error('Incomplete configuration')
        }
        // Runtime authority comes only from the captured main-process resolver,
        // never from a similarly named field in the Python response.
        resolve({git: result.git, environment: result.environment, argv: result.argv,
          diffFlags: result.diffFlags, runtime})
      } catch {
        reject(new GitPolicyError('Trusted Git policy returned an invalid result.'))
      }
    })
    child.stdin?.end()
  })
}

export function applyGitPolicyEnvironment(policy: Pick<PolicyResult, 'environment'>, base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env = {...base}
  const controlled = new Set(Object.keys(policy.environment))
  for (const key of Object.keys(env)) {
    const canonical = process.platform === 'win32' ? key.toUpperCase() : key
    if (/^GIT_CONFIG(?:$|_)/.test(canonical) || controlled.has(canonical)) delete env[key]
  }
  return {...env, ...policy.environment}
}

// Electron must support Node mode before it may be used as a transport binary.
// Unknown or disabled fuse metadata fails closed without starting the app.
function assertNodeTransportAvailable(): void {
  if (!process.versions.electron) return
  assertElectronNodeTransportAvailable(process.execPath)
}

export function assertElectronNodeTransportAvailable(binary: string): void {
  const sentinel = Buffer.from('dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX')
  let fd: number | undefined
  try {
    fd = fs.openSync(binary, 'r')
    const chunk = Buffer.alloc(1024 * 1024)
    let prefix = Buffer.alloc(0)
    let position = 0
    for (;;) {
      const length = fs.readSync(fd, chunk, 0, chunk.length, position)
      if (!length) break
      const data = Buffer.concat([prefix, chunk.subarray(0, length)])
      const index = data.indexOf(sentinel)
      if (index >= 0 && data.length > index + sentinel.length + 2) {
        const offset = index + sentinel.length
        const declaredLength = data[offset + 1]
        if (data[offset] !== 1 || declaredLength === 0) break
        if (data.length >= offset + 2 + declaredLength) {
          if (data[offset + 2] === 49) return
          break
        }
      }
      prefix = Buffer.from(data.subarray(Math.max(0, data.length - sentinel.length - 257)))
      position += length
    }
  } catch {
    throw new GitPolicyError('Trusted Node Git transport metadata is unreadable.')
  } finally {
    if (fd !== undefined) {
      try { fs.closeSync(fd) }
      catch { throw new GitPolicyError('Trusted Node Git transport metadata could not be closed.') }
    }
  }
  throw new GitPolicyError('Trusted Node Git transport is unavailable.')
}

export function simpleGitTransport(cwd: string, policy: Pick<PolicyResult, 'git' | 'runtime' | 'environment'>, timeout = 30, maxOutputBytes = 8 * 1024 * 1024,
  gh?: string, base: NodeJS.ProcessEnv = process.env) {
  const runtime = policy.runtime
  if (!runtime || runtime.argsPrefix.length !== 0) throw new GitPolicyError('Trusted Git runtime is unavailable.')
  const script = path.join(runtime.ownerRoot, 'apps', 'desktop', 'assets', 'git-transport.cjs')
  if (!fs.existsSync(script)) throw new GitPolicyError('Trusted Git transport is unavailable.')
  assertNodeTransportAvailable()
  const nonce = randomUUID()
  const eolSources: Record<string, string> = {}
  for (const [key, value] of Object.entries(process.env)) {
    const canonical = process.platform === 'win32' ? key.toUpperCase() : key
    if (value !== undefined && ['GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_NOSYSTEM'].includes(canonical)) eolSources[canonical] = value
  }
  const request = {nonce, python: runtime.command, root: runtime.ownerRoot,
    git: policy.git, cwd: path.resolve(cwd), timeout, eolSources, maxOutputBytes,
    ...(gh ? {gh} : {})}
  const environment = applyGitPolicyEnvironment(policy, base)
  for (const key of Object.keys(environment)) {
    if (['NODE_OPTIONS', 'NODE_PATH', 'ELECTRON_RUN_AS_NODE', '__HERMES_GIT_TRANSPORT_REQUEST'].includes(key.toUpperCase())) delete environment[key]
  }
  environment.ELECTRON_RUN_AS_NODE = '1'
  environment.__HERMES_GIT_TRANSPORT_REQUEST = JSON.stringify(request)
  return {
    binary: [process.execPath, script] as [string, string],
    environment,
    errors(error: Buffer | Error | undefined, result: {exitCode: number; stdErr: Buffer[]; stdOut: Buffer[]}) {
      const stderr = Buffer.concat(result.stdErr)
      if (result.exitCode === 77 && stderr.toString('utf8') === `HERMES_GIT_POLICY_REFUSED:${nonce}\n`) {
        return new GitPolicyError('Repository Git policy refused the operation.')
      }
      const prefix = `\nHERMES_GIT_TRANSPORT_COMPLETE:${nonce}:`
      const offset = stderr.lastIndexOf(prefix)
      const frame = offset >= 0 ? stderr.subarray(offset + Buffer.byteLength(prefix)).toString('utf8') : ''
      const match = /^(-?\d+):(\d+)\n$/.exec(frame)
      if (!match || Number(match[2]) !== offset ||
          (Number(match[1]) < 0 ? 1 : Number(match[1])) !== result.exitCode) {
        return new GitPolicyError('Trusted Git transport did not complete the operation.')
      }
      // The public callback receives the buffers later consumed by SimpleGit's
      // parsers. Remove authenticated control data from those buffers first.
      const originalStderr = stderr.subarray(0, offset)
      result.stdErr.splice(0, result.stdErr.length, ...(originalStderr.length ? [originalStderr] : []))
      // Preserve simple-git's ordinary Git contract: a nonzero result without
      // Git stderr (e.g. diff --exit-code) is parsed normally. Transport startup
      // errors never have an authenticated completion frame.
      if (result.exitCode && offset) return new GitError(undefined, Buffer.concat([...result.stdOut, originalStderr]).toString('utf8'))
      return undefined
    }
  }
}

export interface GitExecutionResult {
  exitCode: number
  stdout: string
  stderr: string
}

// Let the Python execution owner enforce deadlines and reap the entire tree.
// A Node execFile deadline would kill only its direct child on Windows.
export async function executeGit(cwd: string, selectedGit: string | undefined, args: string[],
  maxOutputBytes = 8 * 1024 * 1024): Promise<GitExecutionResult> {
  const policy = {...gitExecutionAuthority(selectedGit), environment: {}}
  const transport = simpleGitTransport(cwd, policy, 30, maxOutputBytes)
  return executeTransport(cwd, args, transport, maxOutputBytes)
}

export async function executeGh(cwd: string, gh: string | null, args: string[],
  base: NodeJS.ProcessEnv): Promise<GitExecutionResult> {
  const policy = {...gitExecutionAuthority(), environment: {}}
  if (!gh) return {exitCode: 127, stdout: '', stderr: 'gh executable unavailable'}
  if (!path.isAbsolute(gh)) throw new GitPolicyError('Trusted GH executable is unavailable.')
  const maxOutputBytes = 8 * 1024 * 1024
  const transport = simpleGitTransport(cwd, policy, 30, maxOutputBytes, gh, base)
  return executeTransport(cwd, args, transport, maxOutputBytes)
}

function executeTransport(cwd: string, args: string[], transport: ReturnType<typeof simpleGitTransport>,
  maxOutputBytes: number): Promise<GitExecutionResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(transport.binary[0], [transport.binary[1], ...args],
      {cwd, env: transport.environment, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']})
    const stdOut: Buffer[] = []
    const stdErr: Buffer[] = []
    let bytes = 0
    let overflow = false
    const collect = (chunks: Buffer[], chunk: Buffer) => {
      bytes += chunk.length
      if (bytes > 2 * maxOutputBytes + 512) overflow = true
      if (!overflow) chunks.push(chunk)
    }
    child.stdout.on('data', chunk => collect(stdOut, chunk))
    child.stderr.on('data', chunk => collect(stdErr, chunk))
    child.once('error', () => reject(new GitPolicyError('Trusted Git transport could not start.')))
    child.once('close', code => {
      if (overflow || code === null) {
        reject(new GitPolicyError('Trusted Git transport returned incomplete output.'))
        return
      }
      const result = {exitCode: code, stdOut, stdErr}
      const error = transport.errors(undefined, result)
      if (error instanceof GitPolicyError) {
        reject(error)
        return
      }
      resolve({exitCode: code, stdout: Buffer.concat(stdOut).toString('utf8'),
        stderr: Buffer.concat(stdErr).toString('utf8')})
    })
  })
}

export async function executeGitChecked(cwd: string, selectedGit: string, args: string[]): Promise<string> {
  const result = await executeGit(cwd, selectedGit, args)
  if (result.exitCode !== 0) {
    throw Object.assign(new Error(result.stderr || 'Git operation failed.'),
      {code: result.exitCode, stdout: result.stdout, stderr: result.stderr})
  }
  return result.stdout
}
