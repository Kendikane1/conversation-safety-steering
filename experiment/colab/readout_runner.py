"""W02 controller and isolated worker. All computation requires explicit invocation."""
from pathlib import Path
from time import monotonic
from uuid import uuid4
import json
import subprocess
import sys
import traceback

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import conversation_state as st
import conversation_environment as environment
import conversation_review as reviews
import readout_artifacts as artifacts
import readout_analysis as analysis
import readout_view as view
from readout_parent import admit, consistent
from readout_science import freeze
from readout_model import Session


def emit(kind, data):
    print('W02_EVENT '+json.dumps(dict(kind=kind,data=data),ensure_ascii=False,allow_nan=False),flush=True)


def inputs():
    manifest=st.read(HERE/'readout_manifest.json')
    for name,h in manifest['files'].items():
        st.require(st.sha((HERE/name).read_bytes())==h,'Changed packaged input '+name)
    return st.read(HERE/'w02_readout_v1.json'),manifest


def cases_file(name):
    return [json.loads(line) for line in (HERE/name).read_text().splitlines()]


def prior_report(ns,r):
    path=r['report_path']
    st.require(path in r['files'],'Parent does not bind its report')
    return st.read(ns/path)


def parent_for(ns,stage,identity,p):
    if stage=='calibrate':
        st.require(identity==p['w01d']['final'],'Expected accepted W01D final receipt')
        return {}
    r=artifacts.receipt(ns,identity)
    if stage in ('compare','verify'):
        expected={'compare':'calibrate','verify':'compare'}[stage]
        st.require(r['stage']==expected and r['status']=='complete','Expected completed '+expected)
        if stage=='verify':
            st.require(prior_report(ns,r)['disposition']=='verification_pending','Identical routing skips verify')
    if stage=='final':
        st.require(r['stage'] in ('compare','verify','disposition') or (r['stage']=='calibrate' and r['status']!='complete'),'Invalid final parent')
    return r


class ReadoutStore(st.Store):
    def budget(self):
        budget=super().budget()
        # Every claimed W02 slot reserves one stock prefill. Only verify requests a reply.
        claimed=budget['generation_attempts']
        budget['gate_prefills_reserved']=claimed
        if self.plan['phase']!='verify':
            budget['generation_attempts']=0
            budget['remaining_generation_slots']=0
        return budget


def store_for(ns,stage):
    folder=ns/'science'/stage
    return ReadoutStore(folder,st.read(folder/'plan.json'))


def budgets(ns):
    result={}
    for stage in artifacts.PHASES:
        if (ns/'science'/stage/'plan.json').exists():
            result[stage]=store_for(ns,stage).budget()
    return result


def save(ns,job,result,rows,data):
    data.update(budgets=budgets(ns),parent=job['parent'],stage=job['stage'],package_sha256=job['bundle'])
    folder=ns/'analysis'/job['stage']/st.digest(data)
    view.save(folder,job['stage'],rows,data)
    result.update(report_path=str((folder/'report.json').relative_to(ns)),analysis_path=str((folder/'analysis.html').relative_to(ns)))
    emit('analysis',{'path':str(folder/'analysis.html'),'sha256':st.sha((folder/'analysis.html').read_bytes())})


def run_science(ns,job,p,old,adopted,history,ak,prior,result,session_factory=None,clock=monotonic):
    stage=job['stage']
    diagnostic=cases_file('w01_diagnostic.jsonl')
    cases=cases_file('w02_calibration.jsonl') if stage=='calibrate' else diagnostic
    specs=[dict(case_id=c['case_id'],slot_id=c['case_id']+'--'+stage,mode='conditional',name='conditional',alpha=.0625,
                max_new_tokens=1024 if stage=='verify' else 0) for c in cases]
    store=ReadoutStore(ns/'science'/stage,dict(phase=stage,package=job['bundle'],parent=job['parent'],protocol=p,
                                           sources_sha256=st.sha((HERE/'readout_manifest.json').read_bytes()),slots=specs))
    terminal=store.path/'technical-stop.json'
    st.require(not terminal.exists(),'A recorded technical stop requires central review; no further model work')
    rows=store.records()
    st.require(not store.unfinished() and all(r['status']=='ok' for r in rows),'Interrupted/failed slot; use recovery and central disposition')
    done={r['case_id'] for r in rows}
    previous=prior_report(ns,prior) if prior else {}
    data={k:previous[k] for k in ('frozen','replay') if k in previous}
    result['status']='orderly_stop'
    session=None
    try:
        if len(done)<len(cases):
            started=clock()
            session=(session_factory or Session)(adopted,old)
            emit('model_ready',getattr(session,'runtime',{}).get('info',{}))
            for i,(case,slot) in enumerate(zip(cases,specs)):
                cid=case['case_id']
                if cid in done:
                    continue
                if clock()-started>=p['seconds'][stage]:
                    data.update(disposition='orderly_stop',next_action='Return partial evidence for review before resuming unclaimed slots')
                    break
                chosen=None
                policy=None
                if stage=='verify':
                    chosen=data['replay']['views'][data['replay']['nominee']][i]
                    st.require(chosen['case_id']==cid,'Verification order differs')
                    policy=dict(arm=data['frozen']['nominee'],cutoff=chosen['cutoff'],score=chosen['score'],decision=chosen['open'],
                                expected_scores={a:data['replay']['views']['common-'+a][i]['score'] for a in ('B','L','U','D')})
                store.claim(slot['slot_id'])
                emit('started',dict(stage=stage,slot=slot,index=i+1,total=len(cases)))
                row={}
                try:
                    row=session.run(case,slot,policy)
                    st.require(row['case_id']==cid and row['status']=='ok','Unexpected slot identity/status: '+str(row.get('error',row.get('status'))))
                    if stage in ('compare','verify'):
                        row['B_error']=analysis.compare_b(row,history['joined'][cid,'conditional'][0])
                    if stage=='verify':
                        st.require(all(abs(row['scores'][a]-s)<=1e-6 for a,s in policy['expected_scores'].items()),'Live readout drift')
                        verify_answer(row,chosen,policy)
                        row.update(control_response=chosen['record']['response'],control_record_sha256=chosen['source_record_sha256'])
                    published=store.complete(slot['slot_id'],row)
                except Exception as exc:
                    if not store.paths(slot['slot_id'])[2].exists():
                        store.complete(slot['slot_id'],dict(row,status='error',error=str(exc),unknown_consumed_work=True))
                    raise
                emit('observation',dict(html=view.observation(published,data.get('frozen',{}).get('thresholds')),record_sha256=st.digest(published)))
                store.snapshot('in_progress')
            finished_session=session
            session=None
            finished_session.close()
            rows=store.records()
            if len(rows)==len(cases):
                st.immutable(store.path/'cohort-complete.json',dict(records_sha256=st.digest(rows),plan_sha256=store.fingerprint))
        if len(rows)==len(cases):
            st.require(st.read(store.path/'cohort-complete.json')==dict(records_sha256=st.digest(rows),plan_sha256=store.fingerprint),'Cohort cleanup or completion evidence missing')
            if stage=='calibrate':
                data['frozen']=freeze(rows,cases,st.read(HERE/'w02_split.json'))
                data.update(disposition='nominee_frozen',next_action='Return calibration receipt for central comparison clearance')
            elif stage=='compare':
                data['replay']=analysis.replay(ak,rows,data['frozen'],history,cases,old['preserved_files']['docs/W01_RUBRIC.md'])
                data['disposition']=data['replay']['disposition']
                data['technical_status']='stock_reproduced'
                data['review_status']='inherited_source_labels'
                data['replay_effect']={ref:data['replay']['paired'][data['replay']['nominee']][ref]['full'] for ref in ('common-B','calibrated-B')}
                data['live_verification']='pending' if data['disposition']=='verification_pending' else 'skipped_identical_routing'
                data['next_action']='Return replay for central review; verify only with separate clearance if routing changed'
            else:
                binding=dict(parent=job['parent'],package=job['bundle'],plan=store.fingerprint,records=st.digest(rows),
                             rubric=st.sha((HERE/'W02_READOUT_RUBRIC.md').read_bytes()))
                data['review_template'],data['review_key']=reviews.template(rows,cases,binding)
                path=store.path/'review-template.json'
                st.immutable(path,data['review_template'])
                data.update(disposition='fresh_review_pending',next_action='Central fills the new verify review envelope for final')
            result['status']='complete'
    except Exception as exc:
        st.immutable(terminal,dict(error=str(exc),plan_sha256=store.fingerprint,observed_utc=st.now()))
        result.update(status='failed',error=str(exc))
        data.update(disposition='technical_incomplete',error=str(exc),next_action='Return partial export for central review')
        raise
    finally:
        try:
            if session:
                session.close()
        finally:
            store.snapshot(result['status'])
            save(ns,job,result,store.records(),data)


def verify_answer(row,chosen,policy):
    require=st.require
    for k in ('generated_ids','response','response_sha256','finish_reason','input_ids','messages_sha256','token_sha256','generation_settings'):
        require(row[k]==chosen['record'][k],'Live/control mismatch '+row['case_id']+' '+k)
    trace=row['trace']
    require(row['gate']==trace['gate_calls'][0] and len(trace['gate_calls'])==1 and row['gate']['decision']==policy['decision'] and
            row['gate']['raw_score']==row['scores'][policy['arm']] and abs(row['gate']['raw_score']-policy['score'])<=1e-6 and
            row['gate']['decision']==(row['gate']['raw_score']>policy['cutoff']), 'Wrong gate consumed')
    n=len(row['generated_ids'])
    require(row['status']=='ok' and row['finish_reason']=='eos_token' and row['generated_ids'][-1]==3 and n<=1024 and
            row['forward_attempts']==row['forward_completions']==n+1 and trace['intervention_calls']==5*n*policy['decision'] and
            row['finite_logits'] and not row['hooks_after'], 'Live accounting/finish/cleanup mismatch')


def finish(ns,job,prior,p,old,history,ak,result):
    result['status']='complete'
    if prior['stage']=='disposition' or prior['status']!='complete':
        phase=prior.get('phase',prior['stage'])
        rows=store_for(ns,phase).records() if phase in artifacts.PHASES and (ns/'science'/phase/'plan.json').exists() else []
        save(ns,job,result,rows,dict(technical_status='incomplete',decision='technical_incomplete',review_status='unavailable',
                                   failed_phase=phase,errors=[prior.get('error')]+[r.get('error') for r in rows if r.get('error')],
                                   next_action='Central reviews the preserved attempt and outstanding claims'))
        return
    compare=prior if prior['stage']=='compare' else artifacts.receipt(ns,prior['parent'])
    previous=prior_report(ns,compare)
    cases=cases_file('w01_diagnostic.jsonl')
    rows=store_for(ns,'compare').records()
    frozen=previous['frozen']
    rubric=old['preserved_files']['docs/W01_RUBRIC.md']
    replay=analysis.replay(ak,rows,frozen,history,cases,rubric)
    st.require(replay==previous['replay'],'Final replay recomputation differs')
    data=dict(replay=replay,frozen=frozen,disposition=replay['disposition'],technical_status='comparison_complete',
              decision=replay['disposition'],review_status='inherited_source_labels',next_action='Central reviews retrospective comparison')
    data['replay_effect']=previous['replay_effect']
    data['live_verification']=previous['live_verification']
    data['baseline_disposition']='retain_deployed_baseline'
    if prior['stage']=='verify':
        rows=store_for(ns,'verify').records()
        expected=prior_report(ns,prior)['review_template']
        preview=job['labels']=='PREVIEW'
        envelope=expected if preview else st.read(job['labels'])
        if not preview:
            raw=Path(job['labels']).read_bytes()
            st.immutable(ns/'analysis/imports'/(st.sha(raw)+'.json'),raw)
            data['label_import']=dict(filename=job['label_filename'],sha256=st.sha(raw),settled_semantic=sum(l['status']=='reviewed' for l in envelope['labels']),
                                      settled_quality=sum(l['quality_status']=='reviewed' for l in envelope['labels']))
            result['label_import']=data['label_import']
            emit('label_import',data['label_import'])
        reviews.validate(envelope,expected,rows)
        live=[]
        joined=reviews.joins(rows,envelope['labels'])
        from lexsi_track2.review import record_key
        for chosen in replay['views'][replay['nominee']]:
            cid=chosen['case_id']
            row,label=joined[cid,'conditional']
            verify_answer(row,chosen,dict(arm=frozen['nominee'],cutoff=chosen['cutoff'],score=chosen['score'],decision=chosen['open']))
            if label:
                for arm in ('base','conditional','always_on'):
                    source,inherited=history['joined'][cid,arm]
                    if source['response']==row['response']:
                        consistent(inherited,label)
            live.append(dict(chosen,record=row,label=label,view_id=record_key(row),eligible=reviews.eligible(row,label),kind='fresh verified generation'))
        pending=reviews.pending(rows,envelope['labels'])
        data.update(live=live,live_metrics=analysis.metrics(ak,live,cases,rubric),live_paired={},review_status='pending' if pending else 'settled',
                    disposition='fresh_responses_verified',technical_status='verification_complete')
        for ref in ('common-B','calibrated-B'):
            reference=replay['views'][ref]
            data['live_paired'][ref]=dict(full=analysis.paired(live,reference),without_witness=analysis.paired(
                [r for r in live if r['case_id']!='f11-disallowed'],[r for r in reference if r['case_id']!='f11-disallowed']))
        data['live_verification']='completed'
        guards=[v['full']['guard'] for v in data['live_paired'].values()]
        data['decision']='pending_review' if pending else 'descriptive_readout_benefit' if all(guards) else 'readout_benefit_criterion_unmet'
        if data['decision']=='descriptive_readout_benefit':
            data['baseline_disposition']='retrospective_benefit_only'
        data['next_action']='Return final evidence for central review' if not pending else 'Settle the fresh review envelope and repeat final on the same verify parent'
    save(ns,job,result,rows,data)


def worker(job,result):
    p,_=inputs()
    ns=Path(job['namespace'])
    stage=job['stage']
    old,adopted=environment.worker_admission(job,result,stage in artifacts.PHASES)
    sys.path.insert(0,str(adopted['root']/'src'))
    history=admit(Path(job['private'])/'conversation-results'/p['w01d']['package'],p)
    from lexsi_track2.setup import load_auditkit
    ak=load_auditkit(adopted['root'])
    emit('admitted',dict(parent=job['parent'],stage=stage))
    prior=parent_for(ns,stage,job['parent'],p)
    if stage=='final':
        finish(ns,job,prior,p,old,history,ak,result)
    else:
        run_science(ns,job,p,old,adopted,history,ak,prior,result)


def dispatch(job,report,folder,old):
    """Restore the accepted environment, then admit and execute inside its interpreter."""
    gpu=environment.gpu
    private=Path(job['private'])
    scientific=job['stage'] in artifacts.PHASES
    adopted,local,prefix,env,snapshot=environment.prepare(private,old,report,scientific)
    job['snapshot']=str(snapshot) if snapshot else None
    request,answer=folder/'request.json',folder/'worker.json'
    st.immutable(request,job)
    cmd=[str(prefix/'bin/python'),'-I','-B','-u',str(HERE/'readout_runner.py'),'worker',str(request),str(answer)]
    with subprocess.Popen(cmd,cwd=HERE,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) as proc:
        try:
            for line in proc.stdout:
                clean=line if line.startswith('W02_EVENT ') else gpu.v2.diagnostic(line)
                print(clean.rstrip(),flush=True)
                if line.startswith('W02_EVENT ') and json.loads(line[len('W02_EVENT '):])['kind']=='admitted':
                    st.atomic(local/'current',prefix.name.encode())
            code=proc.wait()
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
    st.require(answer.is_file(),'Worker stopped before publication; preserve reservations')
    report.update(st.read(answer))
    st.require(code==0 and report['status']!='failed',report.get('error','Worker failure'))


def controller(job,execute=dispatch):
    stage,bundle,private=job['stage'],job['bundle'],Path(job['private'])
    st.require(len(bundle)==64 and all(c in '0123456789abcdef' for c in bundle),'Invalid package SHA')
    ns=private/'readout-results'/bundle
    job=dict(job,namespace=str(ns))
    if stage=='export':
        return artifacts.export(ns,job['parent'])
    if stage=='recover':
        return artifacts.recover(ns)
    st.require(stage in artifacts.STAGES and job['reference'].startswith(stage+' ') and job['reference'][len(stage):].strip(),'Stage-specific central reference required')
    p,manifest=inputs()
    if stage=='disposition':
        phase=job['parent']
        st.require(phase in artifacts.PHASES,'Unknown phase')
        store=store_for(ns,phase)
        store.disposition(job['slot'],job['reference'])
        store.snapshot('technical_incomplete')
        parent=store.plan['parent']
        pointer=ns/'pointers'/(phase+'.json')
        if pointer.exists():
            parent=st.read(pointer)['sha256']
            artifacts.receipt(ns,parent)
        identity=artifacts.publish(ns,stage,dict(parent=parent,status='complete',decision='technical_incomplete',reference=job['reference'],
                                                  slot=job['slot'],phase=phase,bundle=bundle,budgets=budgets(ns)))
        return artifacts.export(ns,stage,identity)
    prior=parent_for(ns,stage,job['parent'],p)
    pointer=ns/'pointers'/(stage+'-complete.json')
    if stage in artifacts.PHASES and pointer.exists():
        identity=st.read(pointer)['sha256']
        r=artifacts.receipt(ns,identity)
        st.require(r['parent']==job['parent'],'Different completed ancestry')
        return artifacts.export(ns,stage,identity)
    if stage in artifacts.PHASES:
        anchor=private/'readout-results/protocols'/p['protocol']
        anchor.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive directory binds protocol budget across different package namespaces.
        try:
            anchor.mkdir()
        except FileExistsError:
            st.require((anchor/'identity.json').is_file(),'Interrupted protocol claim; central recovery required')
        st.immutable(anchor/'identity.json',dict(package=bundle,protocol_sha256=st.sha((HERE/'w02_readout_v1.json').read_bytes())))
    for n in manifest['files']:
        if n.startswith(('readout_','w02_','W02_')):
            st.immutable(ns/'inputs'/n,(HERE/n).read_bytes())
    st.immutable(ns/'inputs/readout_manifest.json',(HERE/'readout_manifest.json').read_bytes())
    old=st.read(HERE/'w01_conversation_v1.json')
    attempt=uuid4().hex
    folder=ns/'attempts'/attempt
    report=dict(stage=stage,parent=job['parent'],reference=job['reference'],status='failed',bundle=bundle,attempt=attempt,started_utc=st.now())
    try:
        # Verify all immutable W01D bytes before any restoration or worker dispatch.
        base=private/'conversation-results'/p['w01d']['package']
        accepted=artifacts.receipt(base,p['w01d']['final'])
        st.require(accepted['bundle']==p['w01d']['package'] and accepted['parent']==p['w01d']['review'],'Wrong W01D parent')
        for phase in ('final','review','diagnose'):
            h=p['w01d'][phase]
            st.immutable(ns/'parents'/(h+'.json'),(base/'receipts'/(h+'.json')).read_bytes())
        for name in (accepted['labels_path'],str(Path(accepted['analysis_path']).parent/'records.json'),
                     str(Path(accepted['analysis_path']).parent/'metrics.json'),str(Path(accepted['analysis_path']).parent/'decision.json')):
            st.immutable(ns/'parents/w01d'/name,(base/name).read_bytes())
        execute(job,report,folder,old)
    except Exception as exc:
        report.update(status='failed',error=str(exc),traceback=traceback.format_exc())
        emit('failure',dict(error=str(exc),attempt=attempt))
    report['finished_utc']=st.now()
    report['budgets']=budgets(ns)
    st.immutable(folder/'controller.json',report)
    h=artifacts.publish(ns,stage,report)
    emit('receipt',dict(stage=stage,status=report['status'],outer_sha256=h,error=report.get('error')))
    return artifacts.export(ns,stage,h)


if __name__=='__main__':
    if sys.argv[1]=='worker':
        result={}
        try:
            worker(st.read(sys.argv[2]),result)
        except Exception as exc:
            result.update(status='failed',error=str(exc),traceback=traceback.format_exc())
        st.immutable(Path(sys.argv[3]),result)
    else:
        import signal
        def interrupt(signum,frame):
            raise InterruptedError('Operator interrupted this controller')
        signal.signal(signal.SIGTERM,interrupt)
        emit('export',controller(st.read(sys.argv[2])))
