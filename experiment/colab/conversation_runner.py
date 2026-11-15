"""Isolated W01D controller/worker. Imports are inert; execution is explicit."""
from pathlib import Path
import json
import os
import subprocess
import sys
import traceback
from uuid import uuid4

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import conversation_state as st
import conversation_environment as environment
import conversation_compute as compute
import conversation_review as reviews
import conversation_view as view
import conversation_artifacts as artifacts
import conversation_model as model_work
import gpu_runner as gpu

PREFIX='W01D_EVENT '


def emit(kind,data):
    print(PREFIX+json.dumps({'kind':kind,'data':data},ensure_ascii=False,allow_nan=False),flush=True)


def namespace(private,bundle):
    st.require(len(bundle)==64 and all(c in '0123456789abcdef' for c in bundle),'Invalid bundle SHA')
    return private/'conversation-results'/bundle


def initialize(ns,manifest):
    for name in manifest['files']:
        if name.startswith('conversation_') or name in ('w01_conversation_v1.json','W01_CONVERSATION_RUBRIC.md','w01_diagnostic.jsonl','W01_RUBRIC.md'):
            st.immutable(ns/'inputs'/name,(HERE/name).read_bytes())
    st.immutable(ns/'inputs/conversation_manifest.json',(HERE/'conversation_manifest.json').read_bytes())


def store_from(ns,phase):
    path=ns/'science'/phase
    return st.Store(path,st.read(path/'plan.json'))


def complete_receipt(ns,phase,parent):
    result=artifacts.receipt(ns,parent)
    st.require(result['stage']==phase and result['status']=='complete','Expected completed '+phase+' receipt')
    return result


def receipt_records(ns,receipt):
    if not receipt.get('review_template_path'):return []
    path=Path(receipt['review_template_path']).parent/'records.json'
    st.require(str(path) in receipt['files'],'Receipt does not bind its review records')
    return st.read(ns/path)


def binding(protocol,store,rows):
    return dict(protocol_sha256=st.sha((HERE/'w01_conversation_v1.json').read_bytes()),plan_sha256=store.fingerprint,
                records_sha256=st.digest(rows),baseline_rubric_sha256=protocol['preserved_files']['docs/W01_RUBRIC.md'],
                quality_rubric_sha256=st.sha((HERE/'W01_CONVERSATION_RUBRIC.md').read_bytes()))


def budget_summary(ns):
    return {phase:store_from(ns,phase).budget() for phase in ('diagnose',) if (ns/'science'/phase/'plan.json').exists()}


def review_outputs(ns,protocol,store,cases,extra):
    rows=store.records()
    h,checkpoint=store.snapshot(extra['status'],extra)
    folder=ns/'analysis'/store.plan['phase']/h
    template,key=reviews.template(rows,cases,binding(protocol,store,rows))
    st.immutable(folder/'review-template.json',template);st.immutable(folder/'review-key.json',key)
    st.immutable(folder/'records.json',rows)
    routes=observed_routes(rows)
    decision=reviews.analyze(protocol,rows,[],cases,extra['status']=='complete',routes)
    view.save_view(folder,protocol,rows,cases,decision=decision,budgets=budget_summary(ns))
    hidden='<!doctype html><meta charset="utf-8"><h1>Arm-hidden review — fresh reviewer only</h1><p>The full bundle contains condition mappings. Record prior exposure honestly.</p>'
    import html
    for label in template['labels']:
        hidden+='<details><summary>'+html.escape(label['review_id'])+'</summary><pre>'+html.escape(json.dumps(label,ensure_ascii=False,indent=2))+'</pre></details>'
    st.immutable(folder/'arm-hidden-review.html',hidden.encode())
    emit('analysis',{'path':str(folder/'analysis.html'),'sha256':st.sha((folder/'analysis.html').read_bytes())})
    return {'checkpoint_sha256':h,'review_template_path':str((folder/'review-template.json').relative_to(ns)),
            'analysis_path':str((folder/'analysis.html').relative_to(ns))}


def parent_files(ns,adopted,protocol):
    private=adopted['root'].parents[3]
    # Explicit canonical paths, not a broad search of the user's Drive.
    folder=private/'isolated-results'/protocol['parent_package']
    keys=[protocol['parent_decode']]
    p=adopted['references']['decode']['parent']
    for _ in range(4):
        keys.append(p);p=gpu.v3.receipt(folder,p)['parent']
    for key in keys:st.immutable(ns/'parents'/(key+'.json'),(folder/(key+'.json')).read_bytes())
    for phase in ('tokenizer','smoke','calibration','prefill','decode'):
        st.immutable(ns/'parents'/('checkpoint-'+phase+'.json'),(adopted['root']/'chain'/(phase+'.json')).read_bytes())
    for filename in ('manifest.json','assets.json'):
        st.immutable(ns/'parents'/('calibration-'+filename),(adopted['calibration']/filename).read_bytes())
    st.immutable(ns/'parents/references.json',adopted['references'])
    history=adopted['length_parent'];old=Path(history['namespace'])
    for name,h in history['receipts']['final']['files'].items():
        raw=(old/name).read_bytes();st.require(st.sha(raw)==h,'W01L evidence changed during copy')
        st.immutable(ns/'parents/w01l'/name,raw)
    for key in (protocol['parent_final'],protocol['parent_confirmation'],protocol['parent_selection'],protocol['parent_comparison']):
        st.immutable(ns/'parents/w01l/receipts'/(key+'.json'),(old/'receipts'/(key+'.json')).read_bytes())
    st.immutable(ns/'parents/accepted-baseline.json',history)
    st.immutable(ns/'parents/W01L_CONFIRM_LABELS.json',(HERE/'W01L_CONFIRM_LABELS.json').read_bytes())


def ingest_labels(job,expected,rows,result):
    preview=job.get('label_mode')=='preview'
    st.require(preview or bool(job.get('labels')),'Filled labels required; choose explicit preview for pending-only analysis')
    envelope=expected if preview else st.read(job['labels'])
    reviews.validate(envelope,expected,rows)
    labels=envelope['labels']
    info=dict(mode='PENDING-ONLY PREVIEW; no decision ready' if preview else 'validated import',
              filename=Path(job['labels']).name if not preview else None,
              sha256=st.sha(Path(job['labels']).read_bytes()) if not preview else None,
              quality_reviewed=sum(r['quality_status']=='reviewed' for r in labels),
              semantic_reviewed=sum(r['status']=='reviewed' for r in labels),
              capped_exclusions=sum(r['finish_status']=='truncated' for r in labels))
    result['label_import']=info;emit('label_import',info)
    return envelope


def observed_routes(rows):
    routes=[]
    for row in rows:
        if row['slot']['mode']!='conditional':continue
        try:routes.append(model_work.routing_check(row,rows))
        except Exception as exc:routes.append(dict(case_id=row['slot']['case_id'],equal=False,error=str(exc)))
    return routes


def technical(ns,protocol,prior,rows):
    routes=observed_routes(rows)
    if prior.get('status')!='complete' or len(rows)!=96:return False,routes,['Incomplete diagnostic receipt/cohort']
    try:
        store=store_from(ns,'diagnose');current=compute.verify_rows(store,protocol)
        st.require(rows==current,'Review snapshot differs from complete committed cohort')
        st.require(st.read(store.path/'cohort-complete.json')==dict(plan_sha256=store.fingerprint,records_sha256=st.digest(rows)),'Missing/changed final completion marker')
        routes=[model_work.routing_check(r,rows) for r in rows if r['slot']['mode']=='conditional']
        st.require(len(routes)==32 and all(r['equal'] for r in routes),'Incomplete routing checks')
        return True,routes,[]
    except Exception as exc:return False,routes,[str(exc)]


def analyze_parent(ns,protocol,prior,cases,envelope):
    rows=receipt_records(ns,prior)
    good,routes,errors=technical(ns,protocol,prior,rows)
    decision=reviews.analyze(protocol,rows,envelope['labels'],cases,good,routes)
    decision['technical_errors']=errors
    return rows,decision


def worker(job,result):
    phase=job['stage'];ns=Path(job['namespace']);scientific=phase=='diagnose'
    protocol,adopted=environment.worker_admission(job,result,scientific)
    _,manifest=environment.inputs();parent_files(ns,adopted,protocol)
    cases=compute.cases(adopted,protocol)
    emit('admission_ok',{'runtime':result.get('target_host',{}),'continuity':result.get('continuity'),
                         'parent_final':protocol['parent_final'],'scope':protocol['scope'],
                         'budgets':protocol['budget'],'cache_reused':job['snapshot'] is not None})
    if scientific:
        st.require(job['parent']==protocol['parent_final'],'Wrong W01L final parent')
        plan=compute.plan(protocol,phase,manifest,job['bundle'])
        original=st.read(adopted['root']/'configs/w01_baseline.json')
        plan['derived_configuration']=model_work.derived_config(original,protocol)
        plan['arm_configurations']={st.digest(model_work.effective_config(plan['derived_configuration'],slot)):
                                    model_work.effective_config(plan['derived_configuration'],slot) for slot in plan['slots']}
        store=st.Store(ns/'science'/phase,plan);outcome={'status':'failed'}
        try:outcome=compute.run(store,adopted,protocol,emit)
        except Exception as exc:outcome.update(error=gpu.v2.diagnostic(str(exc)),traceback=gpu.v2.diagnostic(traceback.format_exc()))
        finally:result.update(outcome,**review_outputs(ns,protocol,store,cases,outcome))
        return
    from lexsi_track2.setup import load_auditkit
    ak=load_auditkit(adopted['root']);prior=artifacts.receipt(ns,job['parent'])
    if phase=='review':
        st.require(prior['stage'] in ('diagnose','disposition'),'Review requires diagnostic or disposition receipt')
        rows=receipt_records(ns,prior)
        expected=(st.read(ns/prior['review_template_path']) if prior.get('review_template_path') else
                  reviews.template(rows,cases,dict(failed_diagnostic_receipt=job['parent']))[0])
        envelope=ingest_labels(job,expected,rows,result)
        rows,decision=analyze_parent(ns,protocol,prior,cases,envelope)
        diagnostic_parent=job['parent']
    elif phase=='final':
        if prior['stage']=='review':
            st.require(prior['status']=='complete','Final needs completed review; use failed diagnose/disposition for technical reporting')
            diagnostic_parent=prior['diagnostic_parent'];source=artifacts.receipt(ns,diagnostic_parent)
            envelope=st.read(ns/prior['labels_path'])
            rows,decision=analyze_parent(ns,protocol,source,cases,envelope)
            st.require(decision==prior['decision'],'Final recomputation differs from accepted review')
        else:
            st.require(prior['stage']=='disposition' or (prior['stage']=='diagnose' and prior['status']!='complete'),'Final requires review, failed diagnose or disposition')
            diagnostic_parent=job['parent'];rows=receipt_records(ns,prior)
            envelope=reviews.template(rows,cases,dict(technical_parent=job['parent']))[0]
            rows,decision=analyze_parent(ns,protocol,dict(prior,status='failed'),cases,envelope)
    else:raise ValueError('Unsupported worker stage')
    folder=ns/'analysis'/phase/st.digest(dict(parent=job['parent'],envelope=envelope,decision=decision))
    st.immutable(folder/'review-envelope.json',Path(job['labels']).read_bytes() if phase=='review' and job.get('labels') else envelope)
    st.immutable(folder/'decision.json',decision)
    metric=reviews.metrics(ak,rows,envelope['labels'],cases,protocol['preserved_files']['docs/W01_RUBRIC.md'])
    st.immutable(folder/'metrics.json',metric)
    view.save_view(folder,protocol,rows,cases,envelope['labels'],metric,decision,budget_summary(ns))
    result.update(status='complete',decision=decision,diagnostic_parent=diagnostic_parent,
                  labels_path=str((folder/'review-envelope.json').relative_to(ns)),analysis_path=str((folder/'analysis.html').relative_to(ns)))
    emit('decision',result['decision'])
    emit('analysis',{'path':str(ns/result['analysis_path']),'sha256':st.sha((ns/result['analysis_path']).read_bytes())})


def controller(stage,review,parent,bundle,labels='',slot=''):
    st.require(stage in ('diagnose','review','final','export','disposition'),'Invalid stage')
    private=gpu.v2.PRIVATE;ns=namespace(private,bundle)
    if stage=='export':
        result=artifacts.export(ns,parent);emit('export',result);return result
    protocol,manifest=environment.inputs();initialize(ns,manifest)
    st.require(review.startswith(stage+' ') and review[len(stage):].strip(),'Explicit stage clearance/reference required')
    # Complete computational repeats are pure evidence retrieval, before GPU preparation.
    if stage in ('diagnose',) and (ns/'pointers'/(stage+'-complete.json')).exists():
        r=artifacts.receipt(ns,st.read(ns/'pointers'/(stage+'-complete.json'))['sha256'])
        st.require(r['parent']==parent,'Completed phase has different ancestry')
        if r.get('analysis_path'):
            path=ns/r['analysis_path'];emit('analysis',{'path':str(path),'sha256':st.sha(path.read_bytes())})
        emit('receipt',{'sha256':st.read(ns/'pointers'/(stage+'-complete.json'))['sha256'],'status':'complete','stage':stage,'retrieved':True})
        result=artifacts.export(ns,stage,True);emit('export',result);return result
    if stage=='disposition':
        st.require(parent in ('diagnose',),'Choose interrupted phase')
        store=store_from(ns,parent);store.disposition(slot,review)
        adopted=environment.adopt(private,protocol)
        sys.path.insert(0,str(adopted['root']/'src'))
        cases=compute.cases(adopted,protocol)
        outputs=review_outputs(ns,protocol,store,cases,{'status':'technical_incomplete','disposition':review})
        previous=st.read(ns/'pointers'/(parent+'.json'))['sha256'] if (ns/'pointers'/(parent+'.json')).exists() else protocol['parent_final']
        h,r=artifacts.publish(ns,'disposition',dict(status='complete',phase=parent,parent=previous,review=review,slot=slot,
                decision={'status':'technical_incomplete','reason':'Abandoned without retry; full cap reserved'},**outputs))
        emit('decision',r['decision'])
        result=artifacts.export(ns,'disposition');emit('export',result);return result
    attempt=uuid4().hex;folder=ns/'attempts'/attempt;folder.mkdir(parents=True,exist_ok=True)
    report=dict(status='failed',parent=parent,review=review,bundle=bundle,attempt=attempt,started_utc=st.now())
    try:
        if stage in ('diagnose',):
            st.immutable(private/'conversation-results/protocols'/ (protocol['name']+'.json'),
                         {'protocol_sha256':st.sha((HERE/'w01_conversation_v1.json').read_bytes()),'package_sha256':bundle})
        # Validate phase ancestry before resource-heavy setup.
        if stage=='diagnose':st.require(parent==protocol['parent_final'],'Wrong accepted W01L final SHA')
        elif stage=='review':st.require(artifacts.receipt(ns,parent)['stage'] in ('diagnose','disposition'),'Expected diagnostic receipt')
        elif stage=='final':artifacts.receipt(ns,parent)
        # Preserve verified historical evidence even if later host/native admission fails.
        parent_files(ns,environment.adopt(private,protocol),protocol)
        emit('setup',{'status':'Verified parent evidence; checking runtime/resources and reusing or restoring exact approved environment/cache'})
        adopted,local,prefix,env,snapshot=environment.prepare(private,protocol,report,stage in ('diagnose',))
        emit('readiness',report['readiness'])
        job=dict(stage=stage,parent=parent,review=review,bundle=bundle,namespace=str(ns),private=str(private),
                 snapshot=str(snapshot) if snapshot else None,labels='' if labels=='PREVIEW' else labels,
                 label_mode='preview' if labels=='PREVIEW' else 'import')
        request=folder/'request.json';response=folder/'worker.json';st.immutable(request,job)
        command=[str(prefix/'bin/python'),'-I','-B','-u',str(HERE/'conversation_runner.py'),'worker',str(request),str(response)]
        with (folder/'stream.log').open('w') as log:
            proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                  text=True,bufsize=1,env=env,cwd=str(HERE))
            try:
                for line in proc.stdout:
                    clean=line if line.startswith(PREFIX) else gpu.v2.diagnostic(line)
                    log.write(clean);log.flush()
                    print(clean,end='',flush=True)
                    if line.startswith(PREFIX):
                        event=json.loads(line[len(PREFIX):])
                        if event['kind']=='admission_ok':st.atomic(local/'current',prefix.name.encode())
                code=proc.wait()
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=15)
        report['worker_exit']=code
        if response.exists():report.update(st.read(response))
        st.require(code==0 and response.exists(),'Worker interrupted; return partial bundle and retain claimed slots')
    except Exception as exc:
        report.update(status='failed',error=gpu.v2.diagnostic(str(exc)),traceback=gpu.v2.diagnostic(traceback.format_exc()))
        emit('failure',{'error':report['error'],'attempt':attempt})
    st.immutable(folder/'controller.json',report)
    h,r=artifacts.publish(ns,stage,report)
    result=artifacts.export(ns,stage)
    emit('receipt',{'sha256':h,'status':report['status'],'stage':stage,'next_parent_sha':h})
    emit('export',result)
    return result


if __name__=='__main__':
    if sys.argv[1]=='worker':
        result={}
        try:worker(st.read(sys.argv[2]),result)
        except Exception as exc:
            result.update(status='failed',error=gpu.v2.diagnostic(str(exc)),traceback=gpu.v2.diagnostic(traceback.format_exc()))
            emit('failure',{'error':result['error']})
        finally:st.immutable(Path(sys.argv[3]),result)
    else:
        import signal
        def interrupted(*args):
            raise InterruptedError('Operator interrupted controller; preserve slot reservations')
        signal.signal(signal.SIGTERM,interrupted)
        controller(*sys.argv[2:])
