// Owned Windows Git deadline fixture. No real fetch, Electron or backend.
import assert from 'node:assert/strict'
import childProcess, {execFileSync} from 'node:child_process'
import {createHash, randomUUID} from 'node:crypto'
import {createRequire, syncBuiltinESMExports} from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {setTimeout as pause} from 'node:timers/promises'

export function deadlinePassed(state, code, after) {
  return state==='rejected' && code==='HERMES_GIT_POLICY_REFUSED' &&
    after.length>0 && after.every(p=>p.alive===false&&p.listener_open===false)
}

export function receiptPassed(unchanged, results) {
  return unchanged===true && results.length>0 && results.every(r=>r.result==='PASS')
}

export function nativeCoverage(mode) {
  assert.ok(['git','gh','gh-large','gh-positive','gh-deadline','output','resolver','static'].includes(mode))
  return {large:!['gh-positive','gh-deadline'].includes(mode),ghPositive:mode==='gh'||mode==='gh-positive',
    deadline:['git','gh','gh-deadline'].includes(mode)}
}

export function setupArguments(repo) {
  return [
    ['-C',repo,'init','--initial-branch=fixture'],
    ['-C',repo,'config','user.name','Owned direct transport fixture'],
    ['-C',repo,'config','user.email','owned@example.invalid'],
    ['-C',repo,'add','.'],
    ['-C',repo,'commit','-m','Owned native fixture'],
  ].map(args=>['-c','gc.auto=0','-c','maintenance.auto=false',...args])
}

// This is a pre-spawn registry, not a command-word allowlist. The Job retains
// cleanup authority even if a short-lived process is never observed by psutil.
export function fixtureLaunches(context, executable, args, options={}) {
  const {operation,repo,root,bindings}=context
  const cwd=options.cwd ?? operation
  assert.ok(path.isAbsolute(executable)&&Array.isArray(args)&&args.every(a=>typeof a==='string'))
  const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
  const record=(exe,cmd,workingDirectory=cwd)=>{
    const sha256=bindings[exe.toLowerCase()]
    assert.ok(sha256,'Executable has no frozen binding')
    return {operation,id:context.id,exe,cwd:workingDirectory,cmd,sha256}
  }
  const records=[record(executable,[executable,...args])]
  const pythonWorkers=(pythonArgs,workingDirectory,includeLauncher)=>{
    for(const alias of context.pythonAliases) {
      if(alias!==context.python || includeLauncher) records.push(record(alias,[context.python,...pythonArgs],workingDirectory))
      if(alias!==context.python) records.push(record(alias,[alias,...pythonArgs],workingDirectory))
    }
    if(context.pythonLauncherCwd) {
      assert.equal(context.pythonLauncherCwd,path.join(operation,'runtime'))
      records.push(record(context.python,[context.python,...pythonArgs],context.pythonLauncherCwd))
    }
    for(const binding of context.pythonArgv0Aliases ?? []) {
      assert.ok(context.pythonAliases.includes(binding.exe)&&path.isAbsolute(binding.argv0))
      records.push(record(binding.exe,[binding.argv0,...pythonArgs],workingDirectory))
    }
  }
  if(executable===context.git){
    assert.equal(cwd,repo)
    assert.ok(setupArguments(repo).some(expected=>equal(expected,args)),'Unregistered setup Git argv')
    for(const alias of context.gitAliases ?? []) {
      records.push(record(alias,[executable,...args]))
      records.push(record(alias,[alias,...args]))
      records.push(record(alias,[path.basename(alias),...args]))
    }
  } else if(executable===context.python){
    if(context.sampleArgv && equal(args,context.sampleArgv)) {
      assert.equal(cwd,operation)
    } else {
      assert.deepEqual(args.slice(0,4),['-I','-B','-c',context.policyProgram])
      assert.equal(args.length,8)
      assert.ok(context.runtimeRoots.includes(args[4]))
      assert.equal(cwd,args[4])
      assert.equal(args[5],context.shim)
      assert.equal(args[6],repo)
      assert.ok(Array.isArray(JSON.parse(args[7]))&&JSON.parse(args[7]).every(a=>typeof a==='string'))
    }
    pythonWorkers(args,cwd,false)
  } else if(executable===context.node){
    assert.equal(cwd,repo)
    const request=JSON.parse(options.env?.__HERMES_GIT_TRANSPORT_REQUEST ?? '')
    assert.ok(context.runtimeRoots.includes(request.root))
    assert.equal(args[0],path.join(request.root,'apps/desktop/assets/git-transport.cjs'))
    assert.equal(request.cwd,repo)
    assert.equal(request.python,context.python)
    assert.equal(request.git,context.shim)
    assert.ok(request.gh===undefined||request.gh===context.shim)
    assert.match(request.nonce,/^[a-f0-9-]{36}$/)
    const program=context.transportProgram
    const pythonArgs=['-I','-B','-c',program,JSON.stringify(request),...args.slice(1)]
    pythonWorkers(pythonArgs,request.root,true)
  } else if(executable===context.esbuild){
    assert.equal(cwd,operation)
    assert.deepEqual(args,[`--service=${context.esbuildVersion}`,'--ping'])
  } else {
    throw new Error('Unregistered fixture executable')
  }
  assert.ok(context.id,'Launch requires a fixture operation id')
  return records
}

export function installLaunchRegistrar(context) {
  const registry=path.join(context.operation,'owned launch registry')
  const originals={spawn:childProcess.spawn,execFile:childProcess.execFile,execFileSync:childProcess.execFileSync}
  const register=(executable,args,options={})=>{
    const env={...(options.env ?? process.env),S06_OPERATION_ID:context.id}
    // Python's product timeout owner inherits its runtime cwd. The shim only
    // records that owner's exact taskkill argv targeting its own retained PID;
    // this fixture never invokes taskkill as a cleanup fallback.
    if(executable===context.python&&!context.sampleArgv) env.S06_RUNTIME_ROOT=args[4]
    if(executable===context.node) env.S06_RUNTIME_ROOT=JSON.parse(env.__HERMES_GIT_TRANSPORT_REQUEST).root
    const boundOptions={...options,env,windowsHide:true}
    for(const record of fixtureLaunches(context,executable,args,boundOptions)) {
      const file=path.join(registry,cryptoRandomName()+'.json')
      fs.writeFileSync(file+'.partial',JSON.stringify(record)+'\n',{flag:'wx'})
      fs.renameSync(file+'.partial',file)
    }
    return boundOptions
  }
  childProcess.spawn=(executable,args=[],options={})=>originals.spawn(executable,args,register(executable,args,options))
  childProcess.execFile=(executable,args,options,callback)=>originals.execFile(executable,args,register(executable,args,options),callback)
  childProcess.execFileSync=(executable,args,options)=>originals.execFileSync(executable,args,register(executable,args,options))
  syncBuiltinESMExports()
}

function cryptoRandomName() {
  return `${process.pid}-${randomUUID()}`
}

export function programFromSource(source,name) {
  const match=source.match(new RegExp('const '+name+' = String.raw`([\\s\\S]*?)`'))
  assert.ok(match,'Bound product program is unavailable')
  // JavaScript template literal semantics normalize source line endings.
  return match[1].replace(/\r\n?/g,'\n')
}

// Pure contract checks: no build, process, listener, repository or bundle setup.
if (process.argv[2]==='--self-check') {
  const dead=[{alive:false,listener_open:false}]
  assert.equal(deadlinePassed('rejected','OTHER_ERROR',dead),false)
  assert.equal(deadlinePassed('rejected','HERMES_GIT_POLICY_REFUSED',dead),true)
  assert.equal(deadlinePassed('resolved','HERMES_GIT_POLICY_REFUSED',dead),false)
  assert.equal(deadlinePassed('rejected','HERMES_GIT_POLICY_REFUSED',[{alive:true,listener_open:false}]),false)
  assert.equal(deadlinePassed('rejected','HERMES_GIT_POLICY_REFUSED',[{alive:false,listener_open:true}]),false)
  assert.equal(receiptPassed(false,[{result:'PASS'}]),false)
  assert.equal(receiptPassed(true,[]),false)
  assert.equal(receiptPassed(true,[{result:'FAIL'}]),false)
  assert.equal(receiptPassed(true,[{result:'PASS'}]),true)
  process.stdout.write('9 pure MJS fixture checks passed\n')
  process.exit(0)
}

async function nativeMain() {
const evidence=process.env.S06_EVIDENCE_DIR
assert.ok(evidence&&path.isAbsolute(evidence))
fs.mkdirSync(evidence,{recursive:true})
const root = path.resolve(import.meta.dirname,'../../..')
const owners = ['hermes_cli/_subprocess_compat.py','agent/deadline.py','apps/desktop/electron/git-execution-policy.ts',
  'downstream/security/bounded_process.py',
  'apps/desktop/electron/git-ref-ops.ts','apps/desktop/electron/git-ipc.ts',
  'apps/desktop/electron/git-worktree-ops.ts','apps/desktop/electron/git-review-ops.ts',
  'apps/desktop/electron/main.ts',
  'apps/desktop/assets/git-transport.cjs','tests/windows/fixtures/s06_git_proxy_windows.go',
  'tests/windows/fixtures/s06_desktop_direct_native.mjs','tests/windows/fixtures/run_s06_desktop_direct_native.py']
const digest = p => createHash('sha256').update(fs.readFileSync(path.join(root,p))).digest('hex')
const hashes = Object.fromEntries(owners.map(p=>[p,digest(p)]))
const temp = process.env.S06_OPERATION_ROOT
assert.ok(temp && path.isAbsolute(temp) && path.dirname(path.resolve(temp))===path.join(root,'tmp') &&
  path.basename(temp).startsWith('s06-direct-owned-'))
assert.equal(path.resolve(process.cwd()),path.resolve(temp),'Fixture must start inside its operation root')
const repo = path.join(temp,'owned spaced repo')
fs.mkdirSync(repo)
const python = process.env.S06_PYTHON
const git = process.env.S06_GIT
const shim = process.env.S06_GIT_SHIM
assert.ok([python,git,shim].every(p=>p&&path.isAbsolute(p)))
const digestFile = p => createHash('sha256').update(fs.readFileSync(p)).digest('hex')
const goFixture = {source_sha256:hashes['tests/windows/fixtures/s06_git_proxy_windows.go'],
  exe_sha256:digestFile(shim)}
assert.equal(goFixture.source_sha256,process.env.S06_GO_SOURCE_SHA256)
assert.equal(goFixture.exe_sha256,process.env.S06_GO_EXE_SHA256)
assert.equal(path.dirname(path.resolve(shim)),path.resolve(temp))

process.env.ESBUILD_BINARY_PATH=process.env.S06_ESBUILD
const require = createRequire(path.join(process.env.S06_DESKTOP_DEPS,'package.json'))
const esbuildModule=require('esbuild')
const rawProgram=(file,name)=>{
  const source=fs.readFileSync(file,'utf8')
  return programFromSource(source,name)
}
const context={operation:temp,repo,root,python,git,shim,node:process.execPath,
  esbuild:process.env.S06_ESBUILD,esbuildVersion:esbuildModule.version,
  bindings:JSON.parse(process.env.S06_EXECUTABLE_BINDINGS),
  pythonAliases:JSON.parse(process.env.S06_PYTHON_ALIASES),gitAliases:JSON.parse(process.env.S06_GIT_ALIASES),
  pythonLauncherCwd:path.join(temp,'runtime'),pythonArgv0Aliases:JSON.parse(process.env.S06_PYTHON_ARGV0_ALIASES),
  runtimeRoots:[root,...['missing-static-controls','changed-static-controls'].map(name=>path.join(temp,name+' owned runtime'))],
  policyProgram:rawProgram(path.join(root,'apps/desktop/electron/git-execution-policy.ts'),'policyProgram'),
  transportProgram:rawProgram(path.join(root,'apps/desktop/assets/git-transport.cjs'),'program'),id:'setup'}
for(const [executable,digest] of Object.entries(context.bindings)) assert.equal(digestFile(executable),digest)
for(const binding of context.pythonArgv0Aliases) {
  assert.equal(fs.realpathSync(binding.argv0).toLowerCase(),binding.exe.toLowerCase())
  assert.equal(digestFile(binding.argv0),context.bindings[binding.exe.toLowerCase()])
}
process.env.ESBUILD_BINARY_PATH=context.esbuild
installLaunchRegistrar(context)

const invoke=async(name,action)=>{
  const previous=context.id
  context.id=name
  process.env.S06_OPERATION_ID=name
  try { return await action() }
  finally { context.id=previous; process.env.S06_OPERATION_ID=previous }
}


function writeReceipt(results) {
  const unchanged=owners.every(p=>digest(p)===hashes[p]) && digestFile(shim)===goFixture.exe_sha256
  const passed=receiptPassed(unchanged,results)
  fs.writeFileSync(path.join(evidence,process.argv[2]+'.json'),
    JSON.stringify({native_os:process.platform,backend_started:false,temp,mode:process.argv[3],sha256:hashes,
      go_fixture:goFixture,source_unchanged:unchanged,results},null,2)+'\n')
  return passed
}
for(const args of setupArguments(repo)) {
  const operation=args[6]
  if(operation==='add') fs.writeFileSync(path.join(repo,'owned.txt'),'Owned native fixture\n')
  context.id='setup:'+operation
  execFileSync(git,args,{cwd:repo,windowsHide:true,encoding:'utf8',stdio:['ignore','pipe','pipe'],timeout:10000})
}
const markerDir = path.join(temp,'owned process markers')
fs.mkdirSync(markerDir)
process.env.S06_REAL_GIT = git
process.env.S06_SHIM_TREE_MARKERS = markerDir
process.env.S06_SHIM_HANG_FETCH = '1'
globalThis.s06Handlers = new Map()
const {build,stop} = esbuildModule
const bundle = path.join(temp,'ipc.mjs')
const entry = path.join(temp,'entry.mjs')
fs.writeFileSync(entry,`export {registerGitIpc} from ${JSON.stringify(path.join(root,'apps/desktop/electron/git-ipc.ts'))};\nexport {executeGit} from ${JSON.stringify(path.join(root,'apps/desktop/electron/git-execution-policy.ts'))};\n`)
context.id='bundle:ipc'
await build({absWorkingDir:temp,entryPoints:[entry],bundle:true,format:'esm',platform:'node',target:'node24',outfile:bundle,
  nodePaths:[path.join(process.env.S06_DESKTOP_DEPS,'node_modules')],
  banner:{js:"import {createRequire as cr} from 'node:module';const require=cr(import.meta.url);"},
  plugins:[{name:'owned-ipc',setup(builder){
    builder.onResolve({filter:/^electron$/},()=>({path:'electron',namespace:'owned-ipc'}))
    builder.onLoad({filter:/.*/,namespace:'owned-ipc'},()=>({contents:
      'export const ipcMain={handle:(name,fn)=>globalThis.s06Handlers.set(name,fn)}',loader:'js'}))
  }}]})
stop()
const {registerGitIpc,executeGit} = await import(pathToFileURL(bundle).href)
const coverage=nativeCoverage(process.argv[3])
const isGh=['gh','gh-large','gh-positive','gh-deadline'].includes(process.argv[3])
let selectedGh=isGh?shim:null
let selectedRoot=root
registerGitIpc({resolveGitBinary:()=>shim,resolveGhBinary:()=>selectedGh,
  resolveGitPolicyRuntime:()=>({command:python,argsPrefix:[],ownerRoot:selectedRoot})})
const positiveResults=[]
const largePath='owned-large-untracked.txt'
const largeContent='OWNED_LARGE_START\n'+'x'.repeat(9*1024*1024)+'\nOWNED_LARGE_END\n'
if(coverage.large) {
fs.writeFileSync(path.join(repo,largePath),largeContent)
for (const [name,values] of [
  ['hermes:git:review:diff',[repo,largePath,'working',null,false]],
  ['hermes:git:fileDiff',[repo,largePath]]]) {
  const output=await invoke(name,()=>globalThis.s06Handlers.get(name)({},...values))
  assert.ok(Buffer.byteLength(output)>8*1024*1024)
  assert.ok(output.includes('OWNED_LARGE_START')&&output.includes('OWNED_LARGE_END'))
  positiveResults.push({name:name+'-preserves-large-no-index-exit-one',result:'PASS',output_bytes:Buffer.byteLength(output)})
}
fs.unlinkSync(path.join(repo,largePath))
}
if (process.argv[3]==='static') {
  const results=[...positiveResults]
  for (const name of ['missing-static-controls','changed-static-controls']) {
    selectedRoot=path.join(temp,name+' owned runtime')
    fs.mkdirSync(path.join(selectedRoot,'hermes_cli'),{recursive:true})
    fs.mkdirSync(path.join(selectedRoot,'apps/desktop/assets'),{recursive:true})
    fs.writeFileSync(path.join(selectedRoot,'hermes_cli/__init__.py'),'')
    const override=name==='missing-static-controls'
      ? "env=dict(os.environ); env.update({'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'user.name','GIT_CONFIG_VALUE_0':'Owned fixture'}); return env"
      : "env=noninteractive_git_env(); env['GIT_TERMINAL_PROMPT']='1'; return env"
    fs.writeFileSync(path.join(selectedRoot,'hermes_cli/_subprocess_compat.py'),
      fs.readFileSync(path.join(root,'hermes_cli/_subprocess_compat.py'),'utf8')+
      '\ndef noninteractive_repo_git_env(*args, **kwargs):\n    '+override+'\n')
    fs.copyFileSync(path.join(root,'apps/desktop/assets/git-transport.cjs'),
      path.join(selectedRoot,'apps/desktop/assets/git-transport.cjs'))
    const marker=path.join(temp,name+'.operation-marker')
    process.env.S06_OPERATION_MARKER=marker
    let code
    try { await invoke(name,()=>executeGit(repo,shim,['status','--porcelain'])) }
    catch(error) { code=error?.code }
    const passed=code==='HERMES_GIT_POLICY_REFUSED'&&!fs.existsSync(marker)
    results.push({name,result:passed?'PASS':'FAIL',code,operation_marker_exists:fs.existsSync(marker)})
  }
  const passed=writeReceipt(results)
  process.stdout.write(JSON.stringify(results)+'\n')
  process.exit(passed?0:1)
}
if (process.argv[3]==='resolver') {
  const source=fs.readFileSync(path.join(root,'apps/desktop/electron/main.ts'),'utf8')
  const start=source.indexOf('function resolveGhBinary(')
  const end=source.indexOf('\nfunction recentHermesLog(',start)
  assert.ok(start>=0&&end>start)
  const resolveMissing=new Function('path','fileExists','findOnPath','app','process','IS_WINDOWS',
    'let _ghBinaryCache=null;\n'+source.slice(start,end)+'\nreturn resolveGhBinary')(
      path,()=>false,()=>null,{getPath:()=>temp},{env:{ProgramFiles:temp}},true)
  selectedGh=resolveMissing()
  let actual,code
  try { actual=await invoke('resolver:shipInfo',()=>globalThis.s06Handlers.get('hermes:git:review:shipInfo')({},repo)) }
  catch(error) { code=error?.code }
  const passed=JSON.stringify(actual)===JSON.stringify({ghReady:false,pr:null})
  const result={name:'actual-main-gh-resolver-missing-is-unavailable',result:passed?'PASS':'FAIL',
    resolved_value:selectedGh,actual,code}
  const accepted=writeReceipt([...positiveResults,result])
  process.stdout.write(JSON.stringify(result)+'\n')
  process.exit(accepted?0:1)
}
if (coverage.ghPositive) {
  process.env.S06_FAKE_GH='1'
  process.env.GH_TOKEN='OWNED_FAKE_GH_TOKEN'
  const positive=await invoke('gh:positive',()=>globalThis.s06Handlers.get('hermes:git:review:shipInfo')({},repo))
  assert.deepEqual(positive,{ghReady:true,pr:{url:'https://example.invalid/owned',state:'OPEN',number:42}})
  positiveResults.push({name:'gh-preserves-operator-token-selected-git-and-noninteractive-policy',result:'PASS'})
  process.env.S06_FAKE_GH_FAIL='1'
  assert.deepEqual(await invoke('gh:ordinary-refusal',()=>globalThis.s06Handlers.get('hermes:git:review:shipInfo')({},repo)),{ghReady:false,pr:null})
  positiveResults.push({name:'gh-ordinary-authentication-failure-remains-unavailable',result:'PASS'})
  delete process.env.S06_FAKE_GH
  delete process.env.S06_FAKE_GH_FAIL
}
if(['gh-large','gh-positive'].includes(process.argv[3])) {
  const accepted=writeReceipt(positiveResults)
  process.stdout.write(JSON.stringify(positiveResults)+'\n')
  process.exit(accepted?0:1)
}
if (process.argv[3]==='output') {
  const marker=path.join(temp,'finite-output-completed.marker')
  process.env.S06_SHIM_OUTPUT_LIMIT='1'
  process.env.S06_OUTPUT_COMPLETE_MARKER=marker
  let code
  try { await invoke('output:bounded-diff',()=>executeGit(repo,shim,['diff'],1024*1024)) }
  catch (error) { code=error?.code }
  const passed=code==='HERMES_GIT_POLICY_REFUSED'&&!fs.existsSync(marker)
  const result={name:'finite-output-stops-at-stream-limit',result:passed?'PASS':'FAIL',
    refusal_code:code,completion_marker_exists:fs.existsSync(marker)}
  const accepted=writeReceipt([...positiveResults,result])
  process.stdout.write(JSON.stringify(result)+'\n')
  process.exit(accepted?0:1)
}
const sampleProgram = `import importlib.util,json,psutil,sys
spec=importlib.util.spec_from_file_location('s06_listener_observer',sys.argv[3])
observer=importlib.util.module_from_spec(spec); spec.loader.exec_module(observer)
records=json.loads(sys.argv[1]); expected=json.loads(sys.argv[2]); result=[]
for record in records:
    item=dict(record,alive=None,birth=None,listener_open=None,status='UNKNOWN',listener_status='UNKNOWN')
    try:
        p=psutil.Process(record['pid']); birth=p.create_time()
        if str(record['pid']) not in expected or birth==expected[str(record['pid'])]:
            item.update(alive=p.is_running(),birth=birth,exe=p.exe(),cwd=p.cwd(),cmd=p.cmdline(),status='KNOWN')
    except psutil.NoSuchProcess: item.update(alive=False,status='KNOWN')
    except Exception as error: item['process_error']=type(error).__name__
    item.update(observer.listener_probe(record['port']))
    result.append(item)
sys.stdout.write(json.dumps(result))`
const sample = (records,expected={})=>{
  assert.equal(records.length,3,'Listener sample requires the exact owned three-process tree')
  context.sampleArgv=['-I','-B','-c',sampleProgram,JSON.stringify(records),JSON.stringify(expected),
    path.join(root,'tests/windows/fixtures/run_s06_desktop_direct_native.py')]
  const previous=context.id
  context.id='audit:owned-markers'
  try { return JSON.parse(execFileSync(python,context.sampleArgv,
    {cwd:temp,windowsHide:true,encoding:'utf8',stdio:['ignore','pipe','pipe'],timeout:16000})) }
  finally { context.id=previous; context.sampleArgv=null }
}
let operationState = 'pending'
let operationCode
const started = performance.now()
if (isGh) process.env.S06_SHIM_HANG_GH='1'
const operationName=isGh?'hermes:git:review:shipInfo':'hermes:git:fetch'
const operation = invoke(operationName,()=>globalThis.s06Handlers.get(operationName)({},repo,'origin')).then(
  ()=>{operationState='resolved'},error=>{operationState='rejected';operationCode=error?.code})
let records=[]
const readyUntil=performance.now()+10000
while (performance.now()<readyUntil) {
  records=fs.readdirSync(markerDir).filter(p=>p.endsWith('.json')).map(p=>JSON.parse(fs.readFileSync(path.join(markerDir,p),'utf8')))
  if (records.length===3) break
  await pause(50)
}
assert.equal(records.length,3,'Owned Git/child/grandchild did not become ready')
const before=sample(records)
assert.ok(before.every(p=>p.alive&&p.listener_open&&path.resolve(p.cwd)===path.resolve(repo)&&
  path.resolve(p.exe).toLowerCase()===path.resolve(shim).toLowerCase()))
const expected=Object.fromEntries(before.map(p=>[p.pid,p.birth]))
const remainingWait=Math.max(0,35000-(performance.now()-started))
await Promise.race([operation,pause(remainingWait)])
const after=sample(records,expected)
const passed=deadlinePassed(operationState,operationCode,after)
const result={name:(isGh?'direct-gh':'direct-fetch')+'-owned-descendant-deadline',result:passed?'PASS':'FAIL',
  operationState,operationCode,elapsed_ms:performance.now()-started,before,after}
const accepted=writeReceipt([...positiveResults,result])
process.stdout.write(JSON.stringify(result,null,2)+'\n')
// The external birth-verified observer cleans up after recording this assertion.
// A pending operation/remaining child is a behavioral FAIL, never a timeout PASS.
process.exit(accepted?0:1)
}

if (process.argv[1] && path.resolve(process.argv[1])===path.resolve(import.meta.filename)) {
  await nativeMain()
}
