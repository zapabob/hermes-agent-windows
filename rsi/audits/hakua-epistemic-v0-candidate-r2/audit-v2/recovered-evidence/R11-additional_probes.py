"""Additional scoped probes; observations are not promotion gates."""
import copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'execution-copy'))
import compiler,formatter
base=Path(__file__).parent;root=base/'execution-copy';s=compiler.load_snapshot(root/'source_snapshot.json')
rows=[]
q=copy.deepcopy(s);q['candidates'][0]['snapshot_id']='auditor-mismatched-snapshot'
r=compiler.compile_dataset(q);v=compiler.verification_report(q,r,evidence_root=root)
rows.append({'name':'snapshot_row_linkage_mismatch','passed':v['checks']['structural_provenance']['status']=='FAIL' and v['verification_result']=='NEEDS_REVISION','accepted_count':len(r['accepted']),'structural_provenance':v['checks']['structural_provenance'],'verification_result':v['verification_result']})
q=copy.deepcopy(s);q['holdout_registry']=[q['candidates'][0]['candidate_id']]
r=compiler.compile_dataset(q)
rows.append({'name':'candidate_id_registry_out_of_scope','classification':'scope_observation','accepted_count':len(r['accepted']),'limitation':'Registry checks experience_id/source_memory_id, not candidate_id; this is explicitly documented, not claimed complete evaluation exclusion.'})
q=copy.deepcopy(s);a=copy.deepcopy(q['candidates'][0]);b=copy.deepcopy(a);b.update(candidate_id='auditor-other-revision',source_revision_id=1001,revised_claim='Contrary natural-language claim.')
q['candidates']=[a,b];r=compiler.compile_dataset(q)
rows.append({'name':'contradiction_semantics_cross_revision_out_of_scope','classification':'scope_observation','accepted_count':len(r['accepted']),'limitation':'Conflict detection compares revised_claim strings only within the same typed memory/revision key or an explicit unresolved flag; it is not a semantic contradiction reasoner.'})
out={'gating_assertions':1,'gating_passed':sum(x.get('passed') is True for x in rows),'observations':rows,'python_version':sys.version,'compiler_module_path':compiler.__file__,'formatter_module_path':formatter.__file__}
(base/'additional_probe_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
sys.stdout.write(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(0 if out['gating_passed']==out['gating_assertions'] else 1)
