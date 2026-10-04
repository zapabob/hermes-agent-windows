// Pure fixture functions only. Import must not build, spawn or write native evidence.
import assert from 'node:assert/strict'
import {test} from 'node:test'
import path from 'node:path'
import fs from 'node:fs'
import childProcess from 'node:child_process'
import {syncBuiltinESMExports} from 'node:module'
import * as fixture from './s06_desktop_direct_native.mjs'

test('GH stages retain all positive and deadline checks without repeating the large prelude',()=>{
  assert.deepEqual(fixture.nativeCoverage('gh-large'),{large:true,ghPositive:false,deadline:false})
  assert.deepEqual(fixture.nativeCoverage('gh-positive'),{large:false,ghPositive:true,deadline:false})
  assert.deepEqual(fixture.nativeCoverage('gh-deadline'),{large:false,ghPositive:false,deadline:true})
  assert.deepEqual(fixture.nativeCoverage('gh'),{large:true,ghPositive:true,deadline:true})
  assert.throws(()=>fixture.nativeCoverage('unknown'))
  assert.equal(fixture.nativeCoverage('git').large,true)
  assert.equal(fixture.nativeCoverage('git').deadline,true)
})

test('unknown process or listener sample is never accepted',()=>{
  assert.equal(fixture.deadlinePassed('rejected','HERMES_GIT_POLICY_REFUSED',
    [{alive:null,listener_open:null,status:'UNKNOWN'}]),false)
  assert.equal(fixture.deadlinePassed('rejected','HERMES_GIT_POLICY_REFUSED',[]),false)
})

test('setup registers exact init/add/commit argv with repository cwd',()=>{
  const operation=path.resolve('pure-operation')
  const repo=path.join(operation,'owned spaced repo')
  const git=path.join(operation,'git.exe')
  const context={operation,repo,git,id:'setup',bindings:{[git.toLowerCase()]:'git-hash'},gitAliases:[]}
  const commands=fixture.setupArguments(repo)
  for(const args of commands){
    const records=fixture.fixtureLaunches(context,git,args,{cwd:repo})
    assert.deepEqual(records[0].cmd,[git,...args])
    assert.equal(records[0].cwd,repo)
    assert.equal(records[0].operation,operation)
    assert.equal(records[0].sha256,'git-hash')
  }
  assert.throws(()=>fixture.fixtureLaunches(context,git,commands[0],{cwd:path.dirname(operation)}))
  assert.throws(()=>fixture.fixtureLaunches(context,git,['-C',path.dirname(operation),'status'],{cwd:repo}))
})

test('python is bound to exact code, payload and operation cwd',()=>{
  const operation=path.resolve('pure-operation')
  const root=path.resolve('pure-root')
  const repo=path.join(operation,'owned spaced repo')
  const python=path.join(root,'python.exe')
  const shim=path.join(operation,'owned-git.exe')
  const args=['-I','-B','-c','bound-policy-program',root,shim,repo,'["status"]']
  const context={operation,root,repo,python,shim,id:'policy:status',runtimeRoots:[root],
    pythonAliases:[python],policyProgram:'bound-policy-program',
    bindings:{[python.toLowerCase()]:'python-hash'}}
  assert.deepEqual(fixture.fixtureLaunches(context,python,args,{cwd:root})[0].cmd,[python,...args])
  for (const index of [3,4,5,6]) {
    const changed=[...args]; changed[index]='foreign'
    assert.throws(()=>fixture.fixtureLaunches(context,python,changed,{cwd:root}))
  }
  assert.throws(()=>fixture.fixtureLaunches(context,python,args,{cwd:operation}))
})

test('every raw setup command suppresses automatic maintenance without permitting altered argv',()=>{
  const operation=path.resolve('pure-operation'),repo=path.join(operation,'owned spaced repo')
  const git=path.join(operation,'git.exe')
  const context={operation,repo,git,id:'setup',gitAliases:[],bindings:{[git.toLowerCase()]:'git-hash'}}
  const commands=fixture.setupArguments(repo)
  assert.deepEqual(commands.map(args=>args[6]),['init','config','config','add','commit'])
  for(const args of commands) {
    assert.deepEqual(args.slice(0,6),['-c','gc.auto=0','-c','maintenance.auto=false','-C',repo])
    const rows=fixture.fixtureLaunches(context,git,args,{cwd:repo})
    assert.deepEqual(rows[0].cmd,[git,...args])
    const altered=[...args]; altered[3]='maintenance.auto=true'
    assert.throws(()=>fixture.fixtureLaunches(context,git,altered,{cwd:repo}))
  }
})

test('bound template code uses JavaScript CRLF normalization',()=>{
  assert.equal(fixture.programFromSource('const program = String.raw`\r\nknown_code\r\n`','program'),
    '\nknown_code\n')
  assert.throws(()=>fixture.programFromSource('different constant','program'))
})

test('transport registers full python code/request/argv and rejects external authority',()=>{
  const operation=path.resolve('pure-operation'),root=path.resolve('pure-root')
  const repo=path.join(operation,'owned spaced repo'),node=path.join(root,'node.exe')
  const python=path.join(root,'python.exe'),shim=path.join(operation,'owned-git.exe')
  const script=path.join(root,'apps/desktop/assets/git-transport.cjs')
  const request={nonce:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',root,cwd:repo,python,git:shim}
  const context={operation,root,repo,node,python,shim,id:'ipc:fetch',runtimeRoots:[root],
    pythonAliases:[python],transportProgram:'bound-transport-code',
    bindings:{[node.toLowerCase()]:'node-hash',[python.toLowerCase()]:'python-hash'}}
  const records=fixture.fixtureLaunches(context,node,[script,'fetch','origin'],
    {cwd:repo,env:{__HERMES_GIT_TRANSPORT_REQUEST:JSON.stringify(request)}})
  assert.deepEqual(records[1].cmd,[python,'-I','-B','-c','bound-transport-code',JSON.stringify(request),'fetch','origin'])
  assert.equal(records[1].cwd,root)
  for(const key of ['root','cwd','python','git']){
    assert.throws(()=>fixture.fixtureLaunches(context,node,[script,'fetch','origin'],
      {cwd:repo,env:{__HERMES_GIT_TRANSPORT_REQUEST:JSON.stringify({...request,[key]:operation})}}))
  }
})

test('base interpreter alias binds both exact launcher and worker argv identities',()=>{
  const operation=path.resolve('pure-operation'),root=path.resolve('pure-root')
  const repo=path.join(operation,'owned spaced repo'),python=path.join(root,'venv-python.exe')
  const base=path.join(root,'base-python.exe'),shim=path.join(operation,'owned-git.exe')
  const args=['-I','-B','-c','bound-code',root,shim,repo,'["status"]']
  const context={operation,root,repo,python,shim,id:'policy:status',runtimeRoots:[root],
    pythonAliases:[python,base],policyProgram:'bound-code',
    bindings:{[python.toLowerCase()]:'venv-hash',[base.toLowerCase()]:'base-hash'}}
  const records=fixture.fixtureLaunches(context,python,args,{cwd:root})
  assert.deepEqual(records.map(r=>[r.exe,r.cmd[0],r.sha256]),
    [[python,python,'venv-hash'],[base,python,'base-hash'],[base,base,'base-hash']])
  const altered=[...args]; altered[7]='{"foreign":"payload"}'
  assert.throws(()=>fixture.fixtureLaunches(context,python,altered,{cwd:root}))
})

test('Git worker alias binds the exact forwarded launcher argv without broadening setup authority',()=>{
  const operation=path.resolve('pure-operation'),repo=path.join(operation,'owned spaced repo')
  const git=path.join(operation,'cmd','git.exe'),worker=path.join(operation,'ucrt64','bin','git.exe')
  const context={operation,repo,git,id:'setup:git',gitAliases:[worker],
    bindings:{[git.toLowerCase()]:'launcher-hash',[worker.toLowerCase()]:'worker-hash'}}
  const args=fixture.setupArguments(repo)[0]
  const rows=fixture.fixtureLaunches(context,git,args,{cwd:repo})
  assert.ok(rows.some(r=>r.exe===worker && r.sha256==='worker-hash' && r.cwd===repo &&
    JSON.stringify(r.cmd)===JSON.stringify([git,...args])))
  assert.throws(()=>fixture.fixtureLaunches(context,git,[...args,'--foreign'],{cwd:repo}))
  assert.throws(()=>fixture.fixtureLaunches(context,git,args,{cwd:operation}))
  assert.ok(rows.some(r=>r.exe===worker && JSON.stringify(r.cmd)===JSON.stringify(['git.exe',...args])))
})

test('all registered fixture launches force windowsHide even when callers pass false',()=>{
  const operation=path.resolve('pure-operation'),repo=path.join(operation,'owned spaced repo'),git=path.join(operation,'git.exe')
  const context={operation,repo,git,id:'setup',gitAliases:[],bindings:{[git.toLowerCase()]:'bound'}}
  const originals={spawn:childProcess.spawn,execFile:childProcess.execFile,execFileSync:childProcess.execFileSync,
    write:fs.writeFileSync,rename:fs.renameSync}
  const seen=[]
  try {
    for(const name of ['spawn','execFile','execFileSync']) childProcess[name]=(_exe,_args,options)=>{seen.push(options);return {}}
    fs.writeFileSync=()=>{}; fs.renameSync=()=>{}
    fixture.installLaunchRegistrar(context)
    const args=fixture.setupArguments(repo)[0]
    childProcess.spawn(git,args,{cwd:repo,windowsHide:false})
    childProcess.execFile(git,args,{cwd:repo,windowsHide:false},()=>{})
    childProcess.execFileSync(git,args,{cwd:repo,windowsHide:false})
    assert.equal(seen.length,3)
    assert.ok(seen.every(options=>options.windowsHide===true))
  } finally {
    for(const name of ['spawn','execFile','execFileSync']) childProcess[name]=originals[name]
    fs.writeFileSync=originals.write; fs.renameSync=originals.rename
    syncBuiltinESMExports()
  }
})

test('Python launcher runtime cwd and raw interpreter argv0 stay exactly bound',()=>{
  const operation=path.resolve('pure-operation'),root=path.resolve('pure-root'),repo=path.join(operation,'owned spaced repo')
  const python=path.join(root,'venv-python.exe'),base=path.join(root,'versioned-python.exe'),raw=path.join(root,'uv-alias','python.exe')
  const shim=path.join(operation,'owned-git.exe'),runtime=path.join(operation,'runtime')
  const context={operation,root,repo,python,shim,id:'policy:status',runtimeRoots:[root],policyProgram:'bound-code',
    pythonAliases:[python,base],pythonLauncherCwd:runtime,pythonArgv0Aliases:[{exe:base,argv0:raw}],
    bindings:{[python.toLowerCase()]:'venv-hash',[base.toLowerCase()]:'base-hash'}}
  const args=['-I','-B','-c','bound-code',root,shim,repo,'["status"]']
  const rows=fixture.fixtureLaunches(context,python,args,{cwd:root})
  assert.ok(rows.some(r=>r.exe===python&&r.cwd===runtime&&JSON.stringify(r.cmd)===JSON.stringify([python,...args])))
  assert.ok(rows.some(r=>r.exe===base&&r.cwd===root&&r.sha256==='base-hash'&&JSON.stringify(r.cmd)===JSON.stringify([raw,...args])))
  assert.ok(rows.every(r=>r.cwd===root||r.cwd===runtime))
  assert.throws(()=>fixture.fixtureLaunches(context,python,[...args.slice(0,7),'foreign'],{cwd:root}))
  assert.throws(()=>fixture.fixtureLaunches(context,python,args,{cwd:path.join(operation,'other-cwd')}))
})
