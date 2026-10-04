"""Read-only audit of named source records and exported projections."""
from pathlib import Path
import hashlib, json, sqlite3, subprocess, sys
from datetime import datetime, timezone
base=Path(__file__).parent
root=base/'hakua-epistemic-v0-candidate-r2'
repo=Path('C:/Users/downl/Documents/New project/hermes-agent')
canon=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
source=read(root/'source_snapshot.json');prov=read(root/'source_provenance.json')
receipts={'checked_at':datetime.now(timezone.utc).isoformat(),'references':[],'source_lookup':[],'message_exports':[],'related_memory_exports':[],'historical_observations':[]}
for c in source['candidates']:
    entries=[e for e in prov['records'] if all(e.get(k)==c[k] for k in ['experience_id','source_memory_id','source_revision_id'])]
    receipts['references'].append({'candidate_id':c['candidate_id'],'entry_matches':len(entries),'source_record_status':c['source_record_status'],'entry_status':entries[0]['status'] if len(entries)==1 else None,'memory_record_ref':entries[0].get('memory_record_ref') if len(entries)==1 else None,'revision_record_ref':entries[0].get('revision_record_ref') if len(entries)==1 else None,'refs_exactly_linked':len(entries)==1 and entries[0]['evidence_refs']==c['evidence_refs'],'digest_results':[{'ref':ref,'sha256':sha((root/ref).read_bytes()),'matches':len(entries)==1 and entries[0]['file_sha256'].get(ref)==sha((root/ref).read_bytes())} for ref in c['evidence_refs']]})
paths=[Path('C:/Users/downl/.hermes/ebbinghaus_memory.db'),Path('C:/Users/downl/Documents/New project/hakua-memory/.memory/ebbinghaus.db'),Path('C:/Users/downl/Documents/New project/hakua-memory/.memory/semantic.db'),Path('C:/Users/downl/Documents/New project/hakua-memory/.memory/rag.db')]
for path in paths:
    db={'path':str(path),'mode':'ro + PRAGMA query_only=ON','exists':path.exists(),'queries':[]}
    if path.exists():
        con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,cols in [('memories',['memory_id','belief_id']),('memory_events',['memory_id','belief_id']),('memory_provenance',['semantic_memory_id','source_memory_id']),('nodes',['node_id','identity_key']),('memory_node_links',['memory_id','belief_id']),('artifacts',['artifact_id']),('documents',['document_id','source_uri']),('chunks',['chunk_id','document_id'])]:
            if table not in tables:continue
            present={r[1] for r in con.execute('PRAGMA table_info("'+table+'")')}
            cols=[c for c in cols if c in present]
            sql='SELECT count(*) FROM "'+table+'" WHERE '+' OR '.join('CAST("'+c+'" AS TEXT)=?' for c in cols)
            for c in source['candidates']:
                token=c['source_memory_id'];params=[token]*len(cols)
                count=con.execute(sql,params).fetchone()[0]
                db['queries'].append({'sql':sql,'parameters':params,'candidate_id':c['candidate_id'],'exact_alias_matches':count,'claimed_revision':c['source_revision_id'],'revision_resolved':False if count==0 else None})
        if path==paths[0]:
            con.row_factory=sqlite3.Row
            for f in sorted((root/'evidence').glob('related-memory-*.json')):
                exp=read(f);rec=exp['record'];cols=list(rec)
                sql='SELECT '+','.join('"'+c+'"' for c in cols)+' FROM memories WHERE memory_id=?'
                row=con.execute(sql,[rec['memory_id']]).fetchone()
                live=dict(row) if row is not None else None
                receipts['related_memory_exports'].append({'ref':f.relative_to(root).as_posix(),'sql':sql,'parameters':[rec['memory_id']],'found':row is not None,'export_canonical_digest_match':sha(canon(rec))==exp['canonical_record_sha256'],'live_canonical_sha256':sha(canon(live)) if live else None,'export_vs_live_match':live==rec,'changed_fields':[k for k in rec if live is not None and rec[k]!=live[k]],'original_alias_match':any(rec['belief_id']==c['source_memory_id'] or str(rec['memory_id'])==c['source_memory_id'] for c in source['candidates']),'belief_version':rec['belief_version'],'claimed_original_revisions':[c['source_revision_id'] for c in source['candidates'] if f.relative_to(root).as_posix() in c['evidence_refs']],'scope':'Corroboration in mutable local store; thematic relationship does not resolve original alias/revision.'})
        con.close()
    receipts['source_lookup'].append(db)
path=Path('C:/Users/downl/.hermes/state.db')
con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');con.row_factory=sqlite3.Row
for f in sorted((root/'evidence').glob('message-*.json')):
    exp=read(f);loc=exp['source_locator'];sql='SELECT id,session_id,role,tool_name,content FROM messages WHERE id=?'
    row=con.execute(sql,[loc['message_id']]).fetchone()
    text=row['content'] if row is not None else None
    start,end=exp['excerpt_start'],exp['excerpt_end']
    receipts['message_exports'].append({'ref':f.relative_to(root).as_posix(),'sql':sql,'parameters':[loc['message_id']],'source_found':row is not None,'locator_matches':row is not None and all(row[k]==loc[k] for k in ['session_id','role','tool_name']),'span_metadata_valid':0<=start<=end<=exp['source_content_length'] and len(exp['excerpt'])==end-start,'source_length_match':text is not None and len(text)==exp['source_content_length'],'source_hash_match':text is not None and sha(text.encode('utf-8'))==exp['source_content_sha256_utf8'],'source_span_match':text is not None and text[start:end]==exp['excerpt'],'full_content_exported':start==0 and end==exp['source_content_length'],'scope':'Persisted visible content only; no reasoning columns selected. Current local DB corroborates export, not an independent timestamped attestation of historical truth.'})
con.close()
fence=read(root/'evidence/fence-source.json')
argv=['git','-C',str(repo),'show',fence['commit']+':'+fence['source_path']]
r=subprocess.run(argv,capture_output=True,timeout=60)
raw=r.stdout;text=raw.decode('utf-8',errors='replace');start,end=fence['excerpt_start'],fence['excerpt_end']
receipts['historical_git']={'command':argv,'exit_code':r.returncode,'stderr':r.stderr.decode('utf-8',errors='replace'),'git_blob_sha256':sha(raw),'expected_git_blob_sha256':fence['git_blob_sha256'],'blob_digest_match':r.returncode==0 and sha(raw)==fence['git_blob_sha256'],'excerpt_match':r.returncode==0 and text[start:end]==fence['excerpt'],'first_line_match':text[:start].count('\n')+1==fence['first_line'],'last_line_match':text[:end].count('\n')==fence['last_line'],'span_length_match':end-start==len(fence['excerpt'])}
for name in ['asr-wire-observations.json','pid-observations.json']:
    exp=read(root/'evidence'/name);original=repo/exp['original_source_path']
    entry={'ref':'evidence/'+name,'source_path':str(original),'source_exists':original.is_file(),'full_source_sha256_match':None,'projection_matches':None}
    if original.is_file():
        raw=original.read_bytes();entry['actual_full_source_sha256']=sha(raw);entry['full_source_sha256_match']=sha(raw)==exp['original_source_sha256']
        data=json.loads(raw.decode('utf-8'))
        if name.startswith('asr'):
            projections={}
            for condition,part in data['results'].items():
                trials=part['trials']
                projections[condition]={'trials':[{k:v for k,v in t.items() if k in exp['projection_fields']} for t in trials]}
            entry['projection_matches']=projections==exp['results'];entry['freeze_metadata_matches']=data.get('_frozen')==exp['source_freeze_status']
            entry['counts']={condition:{'attempted':len(part['trials']),'transport_valid':sum('error' not in t for t in part['trials']),'decision_valid':sum(t.get('outcome') in {'user_obedient','memory_obedient','other_final'} for t in part['trials']),'truncated_before_final':sum(t.get('finish_reason')=='length' for t in part['trials'])} for condition,part in exp['results'].items()}
            c=exp['results']['C_current_header_imperative']['trials'];entry['C_ASR']=None if not any(t.get('outcome') in {'user_obedient','memory_obedient','other_final'} for t in c) else 'requires_computation';entry['C_length_censoring_count']=sum(t.get('finish_reason')=='length' and t.get('completion_tokens')==2048 and t.get('max_tokens')==2048 for t in c)
        else:
            entry['source_top_level_keys']=list(data)
            entry['observation_values_match']=all(data.get(k)==v for k,v in exp['observations'].items())
            entry['anomaly_matches']=data.get('_anomaly')==exp['anomaly']
    receipts['historical_observations'].append(entry)
parent=repo/'doc/archive/hakua-epistemic-v0-candidate_audit_bundle.zip'
receipts['historical_parent']={'path':str(parent),'exists':parent.exists(),'sha256':sha(parent.read_bytes()) if parent.exists() else None,'expected':'5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa'}
receipts['limitations']=['Queries are exact aliases on explicitly listed identity columns, not a global search or proof of nonexistence.','Read-only local DB/git/probe corroboration shares the producer host and may change independently; no cryptographically signed external attestations were supplied.','No source records/revisions were created or changed; none of these topic records resolve the legacy candidate IDs.']
(base/'source_validation_results.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
sys.stdout.write(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n')
