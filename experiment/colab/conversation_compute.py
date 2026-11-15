"""One-model-per-invocation conversation diagnostic with durable slot budgets."""
import json
from pathlib import Path
import time
import conversation_state as st
import conversation_model as model_work


def plan(protocol,phase,manifest,bundle):
    return dict(schema=1,namespace='W01D',phase=phase,protocol=protocol,
                protocol_sha256=st.digest(protocol),package_sha256=bundle,child_sources=manifest,
                accepted_final=protocol['parent_final'],accepted_decode=protocol['parent_decode'],
                slots=st.slots(protocol,phase),conditions_visible_in_live_notebook=True)


def cases(adopted,protocol):
    from lexsi_track2.contracts import validate_data,diagnostic_coverage
    original=st.read(adopted['root']/'configs/w01_baseline.json')
    result=validate_data(adopted['root'],original)['diagnostic']
    st.require([c['case_id'] for c in result]==protocol['case_order'],'Diagnostic order differs')
    cov=diagnostic_coverage(result)
    st.require((cov['endpoints'],cov['with_prior_refusal'],cov['clarification_only'],cov['anchors'])==(32,16,8,8),'History coverage differs')
    st.require(cov['policy_counts']=={'allow':16,'refuse_harmful_part':16},'Class balance differs')
    return result


def load(adopted,protocol):
    import torch
    from lexsi_track2 import runtime as baseline,contracts
    root=adopted['root'];original=st.read(root/'configs/w01_baseline.json')
    runtime=baseline.load_target(root,original,enabled=True)
    parent=st.read(adopted['calibration']/'manifest.json')
    st.require(contracts.digest(baseline.identity(root,original,'calibration',runtime))==parent['fingerprint'],
               'Live model/calibration fingerprint mismatch')
    for key in ('model_configuration','model_generation_configuration'):
        st.require(contracts.digest(runtime['info'][key])==contracts.digest(parent['hardware'][key]),
                   'Live '+key+' differs from accepted calibration')
    layers=runtime['helpers']._get_decoder_layers(runtime['model'])
    installed=model_work.installed_model_sources(runtime['model'],layers)
    decode_run=adopted['references']['decode_checkpoint']['run_id']
    old=st.read(root/'runs'/decode_run/'installed_source.json')
    st.require({k:{f:v for f,v in r.items() if f!='file'} for k,r in installed.items()}==
               {k:{f:v for f,v in r.items() if f!='file'} for k,r in old.items()},
               'Installed model/generation sources differ from accepted decode')
    runtime['w01d_installed_source']=installed
    saved=torch.load(adopted['calibration']/'vectors.pt',map_location='cpu',weights_only=True)
    assets=st.read(adopted['calibration']/'assets.json')
    st.require({k:assets['condition'][k] for k in protocol['condition']}==protocol['condition'],'Saved condition differs')
    st.require(sorted(saved['behavior'])==protocol['behavior_layers'],'Saved layer keys differ')
    before={}
    for name,tensor in [('condition',saved['condition']),*[(str(k),v) for k,v in saved['behavior'].items()]]:
        st.require(list(tensor.shape)==[2048] and tensor.dtype==torch.float32 and bool(torch.isfinite(tensor).all().item()),
                   'Saved vector shape/dtype/finiteness differs')
        before[name]=st.sha(tensor.detach().float().cpu().contiguous().numpy().tobytes())
    st.require(not model_work.hooks(runtime['model']),'Existing model hooks')
    cfg=model_work.derived_config(original,protocol)
    return runtime,saved,assets,cfg,before


def verify_rows(store,protocol):
    rows=store.records()
    st.require(not store.unfinished(),'Started-but-unfinished generation requires explicit disposition; no automatic retry')
    st.require(not any(r['status'] in ('error','abandoned') for r in rows),'Technical failure/disposition prevents continuation')
    for row in rows:
        validate_record(row,protocol)
        prior=[r for r in rows if r['slot']['case_id']==row['slot']['case_id'] and r['slot']['name']=='base']
        if prior:
            st.require(all(row[k]==prior[0][k] for k in ('messages','input_ids','messages_sha256','serialized_prompt_sha256','token_sha256')),'Triplet prompt identity differs')
        if row['slot']['mode']=='conditional':
            check=model_work.routing_check(row,rows)
            st.require(check['equal'],'Stored conditional routing mismatch; no remaining computation')
            st.require(st.read(store.path/'routing'/(row['slot']['slot_id']+'.json'))==check,'Stored routing evidence differs')
    for path in (store.path/'postconditions').glob('*.json'):
        post=st.read(path)
        st.require(post['saved_vectors_unchanged'] and post['saved_file_unchanged'] and post['parameters_unchanged'] and not post['hooks_after'],'Stored failed postcondition')
    return rows


def validate_record(row,protocol):
    from lexsi_track2.contracts import digest as bd
    slot=row['slot'];ids=row['generated_ids'];n=len(ids);conditional=slot['mode']=='conditional'
    st.require(row['status'] in ('ok','truncated') and 0<n<=1024 and 3 not in ids[:-1],'Bad generated sequence')
    st.require((row['status']=='ok' and row['finish_reason']=='eos_token' and ids[-1]==3) or
               (row['status']=='truncated' and row['finish_reason']=='length' and n==1024 and 3 not in ids),'Bad stopping contract')
    st.require(row['generated_tokens']==n and row['forward_attempts']==row['forward_completions']==n+conditional,'Forward accounting differs')
    st.require(row['finite_logits'] and not row['hooks_after'],'Finiteness/cleanup failure')
    settings={k:v for k,v in protocol['generation'].items() if k not in ('batch_size','max_input_tokens')}
    st.require(row['generation_settings']==settings,'Generation settings differ from frozen protocol')
    st.require(row['alpha']==slot['alpha'] and row['mode']==slot['mode'],'Executed control differs')
    st.require(row['behavior_layers']==protocol['behavior_layers'],'Observed behavior layers differ')
    trace=row['trace'];gate=row.get('gate')
    st.require(len(trace['gate_calls'])==int(conditional),'Gate call count differs')
    if conditional:
        import math
        st.require(gate==trace['gate_calls'][0] and math.isfinite(gate['raw_score']) and
                   gate['decision']==(gate['raw_score']>protocol['condition']['threshold']),'Actual gate evidence differs')
        st.require(row['gate_readout']==model_work.last_pool_metadata(row,protocol),'Last-pool token metadata differs')
    else:st.require(gate is None and row.get('gate_readout') is None,'Unexpected gate call')
    active=slot['mode']=='always_on' or (conditional and gate['decision'])
    st.require(trace['intervention_calls']==(5*n if active else 0) and trace['actual_intervention']==active,'Intervention accounting differs')
    st.require(row['response_sha256']==bd(row['response']) and row['messages_sha256']==bd(row['messages']) and row['token_sha256']==bd(row['input_ids']),'Response/prompt hash differs')
    st.require(0<row['input_tokens']==len(row['input_ids'])<=512,'Invalid input cap')
    st.require(row['serialized_prompt_sha256']==st.sha(row['serialized_prompt'].encode()),'Serialized prompt hash differs')


def run(store,adopted,protocol,emit,clock=time.monotonic):
    cm={c['case_id']:c for c in cases(adopted,protocol)}
    rows=verify_rows(store,protocol);completed={r['slot']['slot_id'] for r in rows}
    runtime=saved=assets=cfg=before=parameters=None
    started=clock();routing=[]
    completion=store.path/'cohort-complete.json'
    if len(completed)==len(store.by_slot):
        st.require(completion.is_file(),'All slots returned but final postconditions were not published; review required, no automatic completion')
        st.require(st.read(completion)=={'plan_sha256':store.fingerprint,'records_sha256':st.digest(rows)},
                   'Cohort completion binding differs')
        return {'status':'complete','retrieved':True}
    finished=False
    try:
        runtime,saved,assets,cfg,before=load(adopted,protocol)
        parameters=model_work.parameter_metadata(runtime['model'])
        from lexsi_track2.contracts import serialize_prompt
        serialized={cid:serialize_prompt(runtime['tokenizer'],c['messages'],512)[1] for cid,c in cm.items()}
        st.immutable(store.path/'full-history-tokenization.json',serialized)
        emit('tokenization',{'cases':32,'maximum_input_tokens':max(p['input_tokens'] for p in serialized.values()),'complete_histories':True})
        st.immutable(store.path/'derived-config.json',cfg)
        if runtime.get('w01d_installed_source'):
            st.atomic(store.path/'installed-source'/(st.digest(runtime['w01d_installed_source'])+'.json'),runtime['w01d_installed_source'])
        st.immutable(store.path/'saved-vectors.json',before)
        emit('model_ready',{'load':runtime['info'],'plan_sha256':store.fingerprint,
                            'reserved_and_known_budget':store.budget()})
        for slot in store.plan['slots']:
            key=slot['slot_id']
            if key in completed:continue
            if clock()-started>=protocol['invocation_seconds']['diagnose']:
                return {'status':'orderly_stop','reason':'Invocation time guard between generations','routing':routing}
            store.claim(key)
            emit('slot_started',{'slot':slot,'budget':store.budget()})
            try:
                result=model_work.generate(runtime,cfg,protocol,cm[slot['case_id']],slot,saved,assets)
            except Exception as exc:
                result={'status':'error','error_type':type(exc).__name__,'error':str(exc),
                        'response':None,'generated_tokens':0,'unknown_consumed_tokens':True}
            effective=model_work.effective_config(cfg,slot)
            expected=st.digest(effective)
            st.require(expected in store.plan['arm_configurations'],'Unplanned arm configuration')
            st.require(result.get('derived_configuration_sha256',expected)==expected,'Executed configuration hash differs')
            result['derived_configuration_sha256']=expected
            row=store.complete(key,result);rows.append(row)
            emit('response',{'record':row,'case':cm[slot['case_id']],
                             'record_sha256':st.sha(store.paths(key)[1].read_bytes()),'budget':store.budget()})
            st.require(row['status'] in ('ok','truncated'),'Generation failed; preserved slot requires review')
            validate_record(row,protocol)
            st.require(all(row[k]==v for k,v in serialized[slot['case_id']].items()),'Generation prompt differs from entry proof')
            base=next(r for r in rows if r['slot']['case_id']==slot['case_id'] and r['slot']['name']=='base')
            st.require(all(row[k]==base[k] for k in ('messages','input_ids','messages_sha256','serialized_prompt_sha256','token_sha256')),'Triplet prompt identity differs')
            if slot['mode']=='conditional':
                route=model_work.routing_check(row,rows);routing.append(route)
                st.immutable(store.path/'routing'/(key+'.json'),route)
                emit('triplet',{'case':cm[slot['case_id']],'records':[r for r in rows if r['slot']['case_id']==slot['case_id']],
                                'record_hashes':{r['slot']['slot_id']:st.sha(store.paths(r['slot']['slot_id'])[1].read_bytes()) for r in rows if r['slot']['case_id']==slot['case_id']},
                                'routing':route,'budget':store.budget()})
                st.require(route['equal'],'Conditional routing sequence mismatch; diagnostic stopped')
        finished=True
        return {'status':'complete','routing':routing}
    finally:
        if runtime is not None:
            import torch
            after={name:st.sha(v.detach().float().cpu().contiguous().numpy().tobytes()) for name,v in
                   [('condition',saved['condition']),*[(str(k),v) for k,v in saved['behavior'].items()]]}
            post=dict(saved_vectors_unchanged=after==before,hooks_after=model_work.hooks(runtime['model']),
                      parameters_unchanged=parameters is not None and model_work.parameter_metadata(runtime['model'])==parameters)
            # Hash the actual original vector file again; no new tensor serialization.
            post['saved_file_unchanged']=st.sha((adopted['calibration']/'vectors.pt').read_bytes())==protocol['vectors_sha256']
            st.atomic(store.path/'postconditions'/(st.digest(post)+'.json'),post)
            emit('cleanup',post)
            st.require(post['saved_vectors_unchanged'] and post['saved_file_unchanged'] and post['parameters_unchanged'] and not post['hooks_after'],
                       'Postcondition failed; preserve evidence')
            if finished:
                st.immutable(completion,{'plan_sha256':store.fingerprint,'records_sha256':st.digest(store.records())})
            del runtime,saved;torch.cuda.empty_cache()
