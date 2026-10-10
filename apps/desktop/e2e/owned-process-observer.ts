import { spawnSync } from 'node:child_process'
import { createConnection } from 'node:net'

/** A hung listener is still open. Only connection refusal proves closure. */
export async function assertLoopbackListenerStopped(url: string): Promise<void> {
  const endpoint = new URL(url)
  if (endpoint.hostname !== '127.0.0.1' || !endpoint.port) {
    throw new Error('Listener audit requires an explicit fixture-owned loopback port')
  }
  await new Promise<void>((resolve, reject) => {
    const socket = createConnection({ host: endpoint.hostname, port: Number(endpoint.port) })
    socket.setTimeout(1_000)
    socket.once('connect', () => {
      socket.destroy()
      reject(new Error('Fixture-owned listener is still open'))
    })
    socket.once('timeout', () => {
      socket.destroy()
      reject(new Error('Listener audit timed out without proving closure'))
    })
    socket.once('error', (error: NodeJS.ErrnoException) => {
      socket.destroy()
      if (error.code === 'ECONNREFUSED') {resolve()}
      else {reject(error)}
    })
  })
}

/** Metadata for exact fixture-owned identities; never enumerate unrelated processes. */
export interface OwnedProcess {
  pid: number
  created: number
  executable: string
  argv: string[]
}

function observe(python: string, source: string, input: unknown): OwnedProcess[] {
  const result = spawnSync(python, ['-I', '-c', source], {
    input: JSON.stringify(input), encoding: 'utf8', timeout: 5_000, windowsHide: true,
  })
  if (result.error || result.status !== 0) {
    throw new Error(`Owned process observer failed: ${result.error ?? result.stderr}`)
  }
  return JSON.parse(result.stdout) as OwnedProcess[]
}

export function captureOwnedTree(python: string, pid: number): OwnedProcess[] {
  return observe(python, [
    'import json, sys, psutil',
    'root = psutil.Process(json.load(sys.stdin))',
    'rows = []',
    'for process in [root, *root.children(recursive=True)]:',
    '    try:',
    '        rows.append(dict(pid=process.pid, created=process.create_time(), executable=process.exe(), argv=process.cmdline()))',
    '    except psutil.NoSuchProcess: pass',
    'print(json.dumps(rows))',
  ].join('\n'), pid)
}

export function survivingOwnedProcesses(python: string, identities: OwnedProcess[]): OwnedProcess[] {
  return observe(python, [
    'import json, sys, psutil, os',
    'rows = []',
    'for identity in json.load(sys.stdin):',
    '    try:',
    '        process = psutil.Process(identity["pid"])',
    '        if process.create_time() == identity["created"] and os.path.normcase(process.exe()) == os.path.normcase(identity["executable"]):',
    '            rows.append(identity)',
    '    except psutil.NoSuchProcess: pass',
    'print(json.dumps(rows))',
  ].join('\n'), identities)
}
