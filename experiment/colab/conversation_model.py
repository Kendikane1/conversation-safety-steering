"""Bounded W01D generations through unmodified pinned CAST; imported only by worker."""
import copy
import time
from conversation_state import require, digest


def derived_config(original,protocol):
    cfg=copy.deepcopy(original)
    cfg['generation']={k:v for k,v in protocol['generation'].items() if k not in ('eos_token_id','pad_token_id')}
    cfg['seed']=protocol['seed']
    return cfg


def effective_config(cfg,slot):
    effective=copy.deepcopy(cfg)
    effective['generation']['max_new_tokens']=slot['max_new_tokens']
    effective['w01d_control']={k:slot[k] for k in ('name','alpha','mode')}
    return effective


def make_cast(runtime,saved,assets,alpha):
    module=runtime['cast_module']
    return module.CASTModel(runtime['model'],saved['behavior'],condition=module.CASTCondition(
        condition_vector=saved['condition'],**assets['condition']),alpha=alpha,per_prompt_gate=True)


def hooks(model):
    import sys
    result={n:{kind:len(getattr(m,kind,{})) for kind in ('_forward_hooks','_forward_pre_hooks')}
            for n,m in model.named_modules() if getattr(m,'_forward_hooks',{}) or getattr(m,'_forward_pre_hooks',{})}
    torch=sys.modules.get('torch')
    if torch is not None:
        global_hooks={n:len(getattr(torch.nn.modules.module,n,{})) for n in ('_global_forward_hooks','_global_forward_pre_hooks')
                      if getattr(torch.nn.modules.module,n,{})}
        if global_hooks:result['__global__']=global_hooks
    return result


def generate(runtime,cfg,protocol,case,slot,saved,assets):
    import torch
    from lexsi_track2.contracts import serialize_prompt,digest as baseline_digest
    from lexsi_track2.runtime import generation_settings
    from lexsi_track2.observe import generate_arm
    require(slot['mode'] in ('base','always_on','conditional'),'Unplanned generation mode')
    cfg=effective_config(cfg,slot)
    model,tok=runtime['model'],runtime['tokenizer']
    require(model.config.max_position_embeddings==protocol['context']['max_position_embeddings'] and
            model.config.sliding_window==protocol['context']['sliding_window'],'Saved context settings differ')
    global_hooks=vars(torch.nn.modules.module)
    require(not any(global_hooks.get(n) for n in ('_global_forward_hooks','_global_forward_pre_hooks')),
            'Foreign global hooks before W01D generation')
    require(not hooks(model),'Foreign hooks before W01D generation')
    cast=make_cast(runtime,saved,assets,slot['alpha'])
    require(list(sorted(cast.steering_vectors))==protocol['behavior_layers'],'Behavior layer mismatch')
    require(cast.pool=='last' and cast.comparator=='smaller' and cast.condition_layer==27
            and cast.threshold==protocol['condition']['threshold'],'Condition mismatch')
    inputs,prompt=serialize_prompt(tok,case['messages'],512)
    require(prompt['input_tokens']+slot['max_new_tokens']<=protocol['context']['max_input_plus_output']<=
            min(model.config.max_position_embeddings,model.config.sliding_window),'Input/output budget exceeds preserved context')
    inputs={k:v.to(model.device) for k,v in inputs.items()}
    pool_metadata=last_pool_metadata(prompt,protocol) if slot['mode']=='conditional' else None
    settings=generation_settings(cfg,tok,model,slot['max_new_tokens'])
    require(settings['eos_token_id']==3 and settings['pad_token_id']==0,'Stopping-token mismatch')
    require(settings['use_cache'] and settings['cache_implementation']=='dynamic' and not settings['do_sample'],'Generation contract differs')
    torch.manual_seed(cfg['seed']);torch.cuda.manual_seed_all(cfg['seed'])
    torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
    counters={'forward_attempts':0,'forward_completions':0}
    finite=None
    def before(*args):
        require(counters['forward_attempts']<slot['max_new_tokens']+(slot['mode']=='conditional'),'Forward budget exceeded before dispatch')
        counters['forward_attempts']+=1
    def after(module,args,out):
        nonlocal finite
        counters['forward_completions']+=1
        current=torch.isfinite(out.logits).all()
        finite=current if finite is None else finite & current
    handles=[model.register_forward_pre_hook(before,with_kwargs=True),model.register_forward_hook(after)]
    start=time.perf_counter();row=dict(prompt,case_id=case['case_id'],alpha=slot['alpha'],mode=slot['mode'],
                                     generation_settings=settings,derived_configuration_sha256=digest(cfg),
                                     messages=case['messages'],gate_readout=pool_metadata,behavior_layers=sorted(cast.steering_vectors),
                                     **{k:case[k] for k in ('scenario_id','category','history_type','has_prior_refusal','prior_refusal_message_indices')})
    try:
        with torch.inference_mode():
            if slot['mode']=='direct':
                cast.install()
                try:output=model.generate(**inputs,**settings)
                finally:cast.remove();cast._row_mask=None
                trace={'gate_calls':[],'observer':'not installed; direct upstream sentinel'}
            else:
                output,trace=generate_arm(model,cast,slot['mode'],inputs,settings)
        torch.cuda.synchronize()
        require(torch.equal(output[0,:prompt['input_tokens']],inputs['input_ids'][0]),'Generated prompt prefix changed')
        ids=output[0,prompt['input_tokens']:].tolist()
        row.update(generated_ids=ids,generated_tokens=len(ids))
        require(0<len(ids)<=slot['max_new_tokens'],'Invalid generated-token count')
        require(3 not in ids[:-1],'Generation continued after EOS')
        reason='eos_token' if ids[-1]==3 else 'length' if len(ids)==slot['max_new_tokens'] else 'unexpected_stop'
        require(reason!='unexpected_stop','Generation stopped without EOS or cap')
        require(finite is not None and bool(finite.item()),'Nonfinite logits')
        gate=trace['gate_calls'][0] if trace['gate_calls'] else None
        if gate is not None:
            import math
            require(math.isfinite(gate['raw_score']),'Nonfinite gate score')
        if slot['mode']!='direct':
            active=slot['mode']=='always_on' or (gate is not None and gate['decision'])
            require(trace['intervention_calls']==(5*len(ids) if active else 0),'Intervention frequency differs from five fixed layers')
        require(counters['forward_attempts']==len(ids)+(slot['mode']=='conditional'),'Model forward/token budget accounting differs')
        require(counters['forward_completions']==counters['forward_attempts'],'Incomplete model forward')
        response=tok.decode(ids,skip_special_tokens=True)
        row.update(response=response,response_sha256=baseline_digest(response),generated_ids=ids,
                   generated_tokens=len(ids),finish_reason=reason,status='ok' if reason=='eos_token' else 'truncated',
                   gate=gate,trace=trace,finite_logits=True)
    except Exception as exc:
        row.update(status='error',error=str(exc),error_type=type(exc).__name__,response=None,
                   unknown_consumed_tokens='generated_ids' not in row)
        row.setdefault('generated_tokens',0)
    finally:
        cast.remove();cast._row_mask=None
        for handle in handles:handle.remove()
        row.update(counters,seconds=time.perf_counter()-start,
                   timing_scope='generation + conditional gate; excludes model load/tokenization; lightweight counters/finiteness',
                   peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                   hooks_after=hooks(model))
        if row['hooks_after'] or cast._handles:
            row.update(status='error',cleanup_error='Hooks remain; stop invocation')
    return row


def last_pool_metadata(prompt,protocol):
    require(prompt['input_tokens']==len(prompt['input_ids']) and prompt['input_tokens']>0,'Invalid unpadded prompt')
    return dict(layer=protocol['condition']['condition_layer'],pool='last',selected_token_count=1,
                serialized_token_index=prompt['input_tokens']-1,token_id=prompt['input_ids'][-1],
                threshold=protocol['condition']['threshold'],comparator='smaller',decision_rule='score > threshold',
                token_role='last serialized non-padding token after add_generation_prompt=True; not necessarily user content',
                source='pinned CAST _gate_fires filters attention_mask, then _pool_hidden last uses h_seq[-1,:]')


def routing_check(row,controls,selected=None):
    gate=row.get('gate')
    require(gate is not None and type(gate.get('decision')) is bool,'Missing actual conditional gate')
    arm='always_on' if gate['decision'] else 'base'
    target=next(r for r in controls if r['slot']['case_id']==row['case_id'] and r['slot']['name']==arm)
    fields=('generated_ids','response','response_sha256','input_ids','messages_sha256','serialized_prompt_sha256',
            'token_sha256','status','finish_reason','generated_tokens','generation_settings')
    differences=[k for k in fields if k not in row or k not in target or row[k]!=target[k]]
    return dict(case_id=row['case_id'],gate=gate,expected_arm=arm,equal=not differences,differences=differences,
                conditional_record_sha256=digest(row),control_record_sha256=digest(target))


def installed_model_sources(model,layers):
    import inspect
    from pathlib import Path
    from conversation_state import sha
    result={}
    for name,fn in [('model_forward',model.forward),('decoder_forward',layers[16].forward),('generation',model.generate)]:
        original=inspect.unwrap(fn);path=inspect.getsourcefile(original)
        require(path is not None,'Installed source unavailable: '+name)
        result[name]=dict(module=original.__module__,qualname=original.__qualname__,signature=str(inspect.signature(fn)),
                          file=path,file_sha256=sha(Path(path).read_bytes()),source=inspect.getsource(original),
                          first_line=inspect.getsourcelines(original)[1])
    return result


def parameter_metadata(model):
    return [dict(name=n,object_id=id(p),version=p._version,shape=list(p.shape),dtype=str(p.dtype),
                 device=str(p.device),requires_grad=p.requires_grad) for n,p in model.named_parameters()]
