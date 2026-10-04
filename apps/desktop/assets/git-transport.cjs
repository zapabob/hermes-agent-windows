// Main-owned SimpleGit transport. Python owns all repository policy and children.
'use strict'
const {spawn} = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

let request
let failed = false
function refuse() {
  failed = true
  if (request && typeof request.nonce === 'string') {
    process.stderr.write(`HERMES_GIT_POLICY_REFUSED:${request.nonce}\n`)
  }
  process.exitCode = 77
}

try {
  request = JSON.parse(process.env.__HERMES_GIT_TRANSPORT_REQUEST || '')
  if (!request || !/^[a-f0-9-]{36}$/.test(request.nonce) ||
      ![request.python, request.git, request.root, request.cwd].every(value =>
        typeof value === 'string' && path.isAbsolute(value)) ||
      !Number.isFinite(request.timeout) || request.timeout <= 0 || request.timeout > 120 ||
      !fs.existsSync(path.join(request.root, 'hermes_cli', '_subprocess_compat.py'))) {
    throw new Error('Invalid Git transport authority')
  }
  const maxOutputBytes = request.maxOutputBytes ?? 8 * 1024 * 1024
  if (!Number.isInteger(maxOutputBytes) || maxOutputBytes < 1 || maxOutputBytes > 32 * 1024 * 1024) {
    throw new Error('Invalid Git output limit')
  }
  const wireLimit = Math.ceil(maxOutputBytes * 8 / 3) + 4096
  if (request.gh !== undefined && (typeof request.gh !== 'string' || !path.isAbsolute(request.gh))) {
    throw new Error('Invalid GH execution authority')
  }
  const env = {...process.env}
  for (const key of Object.keys(env)) {
    if (['NODE_OPTIONS', 'NODE_PATH', 'ELECTRON_RUN_AS_NODE', '__HERMES_GIT_TRANSPORT_REQUEST'].includes(key.toUpperCase())) delete env[key]
  }
  const program = String.raw`
import base64,importlib,json,os,pathlib,sys
request=json.loads(sys.argv[1])
try:
    root=pathlib.Path(request['root']).resolve()
    sys.path.insert(0,str(root))
    owner=importlib.import_module('hermes_cli._subprocess_compat')
    if pathlib.Path(owner.__file__).resolve()!=(root/'hermes_cli'/'_subprocess_compat.py').resolve():
        raise RuntimeError('Git owner mismatch')
    base=dict(os.environ)
    for key in list(base):
        if key.upper() in ('GIT_CONFIG_GLOBAL','GIT_CONFIG_SYSTEM','GIT_CONFIG_NOSYSTEM'):
            del base[key]
    for key,value in request['eolSources'].items():
        base[key]=value
    execution=owner.run_internal_gh if 'gh' in request else owner.run_internal_git
    options={'gh_bin':request['gh']} if 'gh' in request else {}
    result=execution(sys.argv[2:],request['cwd'],timeout=request['timeout'],
                     base=base,git_bin=request['git'],check_policy=True,binary_output=True,
                     max_output_bytes=request.get('maxOutputBytes',8*1024*1024),**options)
    if result.returncode in (124,127):
        raise RuntimeError('Git transport execution unavailable')
except Exception:
    sys.stdout.buffer.write(json.dumps({'nonce':request['nonce'],'completed':False}).encode('utf-8'))
    sys.exit(0)
def encoded(value):
    return base64.b64encode(value if isinstance(value,bytes) else value.encode('utf-8')).decode('ascii')
response={'nonce':request['nonce'],'completed':True,'exitCode':result.returncode,
          'stdout':encoded(result.stdout),'stderr':encoded(result.stderr)}
sys.stdout.buffer.write(json.dumps(response).encode('utf-8'))
`
  const child = spawn(request.python, ['-I', '-B', '-c', program, JSON.stringify(request), ...process.argv.slice(2)],
    {cwd: request.root, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']})
  const chunks = []
  let bytes = 0
  let unexpectedStderr = false
  child.stdout.on('data', chunk => {
    bytes += chunk.length
    if (bytes <= wireLimit) chunks.push(chunk)
  })
  child.stderr.on('data', () => { unexpectedStderr = true })
  child.once('error', refuse)
  child.once('close', code => {
    if (failed) return
    try {
      if (code !== 0 || unexpectedStderr || bytes > wireLimit) throw new Error('Incomplete transport')
      const response = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      if (response.nonce !== request.nonce || response.completed !== true ||
          !Number.isInteger(response.exitCode) || response.exitCode < -128 || response.exitCode > 255) throw new Error('Incomplete Git execution')
      const decode = value => {
        if (typeof value !== 'string') throw new Error('Invalid Git output')
        const buffer = Buffer.from(value, 'base64')
        if (buffer.length > maxOutputBytes || buffer.toString('base64') !== value) throw new Error('Invalid Git output')
        return buffer
      }
      const stdout = decode(response.stdout)
      const stderr = decode(response.stderr)
      process.stdout.write(stdout)
      process.stderr.write(stderr)
      // The public SimpleGit errors callback must distinguish a completed Git
      // result from failure to start this Node helper itself.
      process.stderr.write(`\nHERMES_GIT_TRANSPORT_COMPLETE:${request.nonce}:${response.exitCode}:${stderr.length}\n`)
      process.exitCode = response.exitCode < 0 ? 1 : response.exitCode
    } catch {
      refuse()
    }
  })
} catch {
  refuse()
}
