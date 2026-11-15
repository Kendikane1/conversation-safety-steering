"""Paired retrospective routing replay, independent counts, and AuditKIT evaluation."""
from collections import Counter
from conversation_state import digest, require
from conversation_review import FIELDS, eligible
from readout_science import ARMS, DEPLOYED


def compare_b(row, old):
    require(all(row[k]==old[k] for k in ('case_id','messages','input_ids','token_sha256','serialized_prompt_sha256','messages_sha256')), 'Historical prompt drift on '+old['case_id'])
    err = abs(row['scores']['B']-old['gate']['raw_score'])
    require(err <= 1e-6 and row['stock_decision']==old['gate']['decision']==(row['scores']['B']>DEPLOYED), 'Historical B drift on '+old['case_id'])
    return err


def paired(rows, reference):
    require([r['case_id'] for r in rows]==[r['case_id'] for r in reference], 'Unmatched case order')
    gains, losses, ns = {}, {}, {}
    for field in FIELDS[:-1]:
        pairs = [(r,b) for r,b in zip(rows,reference) if r['eligible'] and b['eligible'] and
                 (field not in ('useful_safe_completion','unnecessary_refusal') or r['policy']=='allow')]
        gains[field]=[r['case_id'] for r,b in pairs if r['label'][field] and not b['label'][field]]
        losses[field]=[r['case_id'] for r,b in pairs if b['label'][field] and not r['label'][field]]
        ns[field]=len(pairs)
    resolved=[i for i in losses['harmful_content'] if next(r['policy'] for r in rows if r['case_id']==i)!='allow']
    return dict(new=gains, resolved=losses, denominators=ns, resolved_disallowed=resolved,
                guard=bool(resolved and not gains['harmful_content'] and not gains['unnecessary_refusal'] and
                           not losses['useful_safe_completion'] and all(r['eligible'] and b['eligible'] for r,b in zip(rows,reference))),
                route_changes=[r['case_id'] for r,b in zip(rows,reference) if r['open']!=b['open']],
                answer_changes=[r['case_id'] for r,b in zip(rows,reference) if r['response_sha256']!=b['response_sha256']],
                score_only=[r['case_id'] for r,b in zip(rows,reference) if r['open']==b['open'] and r['score']!=b['score']])


def metrics(ak, rows, cases, rubric):
    from lexsi_track2.review import evaluate_manual
    groups={'overall':rows,'sensitivity/without_f11-disallowed':[r for r in rows if r['case_id']!='f11-disallowed']}
    for field in ('policy','category','history_type'):
        for key in sorted({r[field] for r in rows}):
            groups[field+'/'+key]=[r for r in rows if r[field]==key]
    result={}
    for key, group in groups.items():
        audited=evaluate_manual(ak,[r['record'] for r in group],[dict(r['label'],review_id=r['view_id']) for r in group if r['label']],cases,rubric)
        counts={}
        for field in FIELDS[:-1]:
            known=[r for r in group if r['eligible'] and (field not in ('useful_safe_completion','unnecessary_refusal') or r['policy']=='allow')]
            n,total=len(known),sum(r['label'][field] for r in known)
            stat=audited['metrics'].get(field,{})
            require(stat.get('count',0)==n and (not n or abs(stat['mean']-total/n)<1e-12),'AuditKIT differs from direct counts')
            counts[field]={'yes':total,'denominator':n}
        quality=Counter()
        confusion=Counter()
        for r in group:
            label=r['label'] or {}
            quality.update([label.get('quality_status','pending')])
            quality.update(invalid=int(bool(label.get('invalid'))),truncated=int(r['record']['status']=='truncated'),
                           pending=int(label.get('status')!='reviewed'),incoherent=int(label.get('coherent') is False),
                           degenerate=int(bool(label.get('degenerate_repetition'))))
            confusion[(r['policy']+'_'+('open' if r['open'] else 'closed'))]+=1
        result[key]=dict(expected=len(group),counts=counts,auditkit=audited,quality=dict(quality),gate_confusion=dict(confusion))
    return result


def replay(ak, measurements, frozen, history, cases, rubric):
    from lexsi_track2.review import record_key
    require(len(measurements)==len(cases)==32 and [r['case_id'] for r in measurements]==[c['case_id'] for c in cases], 'Incomplete diagnostic score cohort')
    views,stats,checks={}, {}, {}
    errors=[compare_b(r,history['joined'][r['case_id'],'conditional'][0]) for r in measurements]
    for threshold,cutoffs in [('common',dict.fromkeys(ARMS,DEPLOYED)),('calibrated',frozen['thresholds'])]:
        for arm in ARMS:
            name=threshold+'-'+arm
            rows=[]
            for m,c in zip(measurements,cases):
                cid=c['case_id']
                score=m['scores'][arm]
                opened=score>cutoffs[arm]
                route='always_on' if opened else 'base'
                source,label=history['joined'][cid,route]
                if name=='common-B':
                    old=history['joined'][cid,'conditional'][0]
                    require(all(source[k]==old[k] for k in ('generated_ids','response','response_sha256')), 'Stock replay differs')
                record=dict(source,arm=name,run_fingerprint=digest([frozen['observations_sha256'],m['plan_sha256'],name]))
                rows.append(dict(case_id=cid, scenario_id=c['scenario_id'],policy=c['expected_policy_action'],category=c['category'],
                                 history_type=c['history_type'], score=score,cutoff=cutoffs[arm],margin=score-cutoffs[arm],
                                 open=opened,route=route,record=record,label=label,eligible=eligible(source,label),
                                 source_record_sha256=digest(next(r for r in history['rows'] if r['slot']==source['slot'])),
                                 response_sha256=source['response_sha256'],view_id=record_key(record),kind='routing replay'))
            views[name]=rows
            stats[name]=metrics(ak,rows,cases,rubric)
    for group,s in stats['common-B'].items():
        accepted_group=group.replace('policy/','expected_policy_action/')
        if not group.startswith('sensitivity/'):
            require(s['auditkit']['metrics']==history['metrics']['groups'][accepted_group]['conditional']['auditkit']['metrics'],'Stock aggregate drift: '+group)
    for name,rows in views.items():
        checks[name]={}
        for ref in ('common-B','calibrated-B'):
            checks[name][ref]=dict(full=paired(rows,views[ref]),without_witness=paired([r for r in rows if r['case_id']!='f11-disallowed'],
                                                                                     [r for r in views[ref] if r['case_id']!='f11-disallowed']))
    nominee='calibrated-'+frozen['nominee']
    families={}
    for name,rows in views.items():
        families[name]={}
        for f in sorted({r['scenario_id'] for r in rows if r['category']!='anchor'}):
            pair=[r for r in rows if r['scenario_id']==f]
            allowed,harm=sorted(pair,key=lambda r:r['policy'])
            families[name][f]=dict(allowed_open=allowed['open'],harmful_open=harm['open'],separation=harm['score']-allowed['score'])
    threshold_recoveries=set(checks['calibrated-B']['common-B']['full']['resolved_disallowed'])
    reference_coverage={}
    for name, resolved in checks.items():
        recoveries=set(resolved['common-B']['full']['resolved_disallowed'])
        reference_coverage[name]=dict(recovered_also_by_threshold_only=sorted(recoveries & threshold_recoveries),
                                      recovered_only_beyond_deployed_and_absent_from_threshold_recoveries=sorted(recoveries-threshold_recoveries),
                                      safe_disallowed_under_both_deployed_and_view=[r['case_id'] for r,b in zip(views[name],views['common-B'])
                                        if r['policy']!='allow' and not r['label']['harmful_content'] and not b['label']['harmful_content']])
    contrasts={}
    for scheme in ('common','calibrated'):
        for arm,ref in (('L','B'),('U','L'),('D','U')):
            first,base=views[scheme+'-'+arm],views[scheme+'-'+ref]
            contrasts[scheme+' '+arm+' vs '+ref]=dict(paired=paired(first,base),score_differences={
                r['case_id']:r['score']-b['score'] for r,b in zip(first,base)})
    return dict(views=views,metrics=stats,paired=checks,families=families,position_contrasts=contrasts,reference_coverage=reference_coverage,max_B_error=max(errors),nominee=nominee,
                disposition='verification_pending' if checks[nominee]['common-B']['full']['route_changes'] else 'identical_routing')
