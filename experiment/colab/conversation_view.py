"""Escaped notebook and portable conversation views; stdlib only."""
from collections import Counter
import csv,html,io,json,hashlib
from conversation_state import atomic,digest,require
from conversation_review import ARMS,joins,counts,analyze


def esc(value):return html.escape(str(value),quote=True)


def table(rows):
    if not rows:return '<p>Pending / no eligible rows.</p>'
    keys=list(dict.fromkeys(k for r in rows for k in r))
    def value(v):return esc(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else 'pending / unscored' if v is None else v)
    return '<div class="scroll"><table><tr>'+''.join('<th>'+esc(k)+'</th>' for k in keys)+'</tr>'+''.join('<tr>'+''.join('<td>'+value(r.get(k))+'</td>' for k in keys)+'</tr>' for r in rows)+'</table></div>'


def history_html(case):
    text='<h4>Complete authored conversation</h4><p>'+esc(case['category']+' · '+case['history_type'])+'</p>'
    for i,m in enumerate(case['messages']):
        kind='final user request' if i==len(case['messages'])-1 else 'authored assistant refusal' if i in case['prior_refusal_message_indices'] else 'authored assistant history' if m['role']=='assistant' else 'authored user history'
        text+='<b>'+esc(f'{i} · {kind}')+'</b><pre>'+esc(m['content'])+'</pre>'
    return text+'<p>Rationale: '+esc(case['rationale'])+'</p><p>Useful safe assistance: '+esc(case['safe_utility_checklist'])+'</p><p>Forbidden assistance: '+esc(case['forbidden_output_criteria'])+'</p>'


def answer_html(row):
    facts={k:row.get(k) for k in ('status','finish_reason','generated_tokens','seconds','peak_allocated_bytes','peak_reserved_bytes','generation_settings','behavior_layers','gate','gate_readout','forward_attempts','trace','error')}
    return '<h4>'+esc(row['slot']['name'])+' · alpha '+esc(row['slot']['alpha'])+'</h4><pre>'+esc(row.get('response') if row.get('response') is not None else '[no completed response]')+'</pre><details><summary>Settings and observed evidence</summary><pre>'+esc(json.dumps(facts,ensure_ascii=False,indent=2))+'</pre></details>'


def response_html(row,case):
    return '<details open><summary>'+esc(case['case_id']+' · '+row['slot']['name'])+'</summary>'+history_html(case)+answer_html(row)+'</details>'


def triplet_html(rows,case,routing=None):
    for r in rows:
        if r.get('response') is not None:
            response_hash=hashlib.sha256(json.dumps(r['response'],sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            require(response_hash==r['response_sha256'],'View response digest differs')
    by={r['slot']['name']:r for r in rows}
    text='<details open><summary>'+esc(case['case_id'])+' · matched three-condition comparison</summary>'+history_html(case)
    text+='<div class="triplet">'+''.join('<section>'+answer_html(by[a])+'</section>' if a in by else '<section><h4>'+esc(a)+'</h4><p>Unattempted</p></section>' for a in ARMS)+'</div>'
    return text+'<p>Exact conditional routing: '+esc(json.dumps(routing,ensure_ascii=False))+'</p></details>'


def gate_svg(protocol,ledger):
    height=85+28*len(ledger);parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1150" height="{height}" role="img"><rect width="100%" height="100%" fill="white"/><text x="10" y="20">Observed gate score (not a harm probability); threshold dashed. Circle=allowed, square=disallowed.</text>']
    scores=[l['gate']['raw_score'] for l in ledger if l['gate']];lo=min([0,*scores]);hi=max([1,*scores]);x=lambda s:540+400*(s-lo)/(hi-lo)
    threshold=x(protocol['condition']['threshold']);parts.append(f'<path d="M{threshold} 40 V{height-15}" stroke="black" stroke-dasharray="5 5"/>')
    for i,l in enumerate(ledger):
        y=60+i*28;label=f"{l['case_id']} | {l['category']} | {l['history_type']}"
        parts.append(f'<text x="10" y="{y}" font-size="11">{esc(label)}</text>')
        if l['gate']:
            xx=x(l['gate']['raw_score']);color='#17668e' if l['policy']=='allow' else '#a64031'
            parts.append(f'<circle cx="{xx}" cy="{y-4}" r="5" fill="{color}"/>' if l['policy']=='allow' else f'<rect x="{xx-5}" y="{y-9}" width="10" height="10" fill="{color}"/>')
            parts.append(f'<text x="960" y="{y}" font-size="11">{l["gate"]["raw_score"]:.5f} / {"open" if l["gate"]["decision"] else "closed"}</text>')
        else:parts.append(f'<text x="960" y="{y}" font-size="11">unobserved</text>')
    return ''.join(parts)+'</svg>'


def bars(title,items):
    # items=(label,numerator,denominator). Null/empty stays unscored, never zero.
    height=60+45*len(items);parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="{height}"><rect width="100%" height="100%" fill="white"/><text x="12" y="25">{esc(title)}</text>']
    for i,(label,n,d) in enumerate(items):
        y=48+45*i;parts.append(f'<text x="12" y="{y+14}" font-size="12">{esc(label)}</text>')
        if n is not None and d:
            parts.append(f'<rect x="400" y="{y}" width="{500*n/d}" height="20" fill="#237391"/><text x="915" y="{y+14}" font-size="12">{n}/{d}</text>')
        else:parts.append(f'<text x="400" y="{y+14}" font-size="12">pending / unscored</text>')
    return ''.join(parts)+'</svg>'


def save_view(folder,protocol,rows,cases,labels=None,metrics=None,decision=None,budgets=None):
    labels=labels or [];metrics=metrics or {};decision=decision or analyze(protocol,rows,labels,cases,False,[])
    ledger=decision['ledger'];bycase={c['case_id']:c for c in cases};joined=joins(rows,labels)
    summaries=[]
    for arm in ARMS:
        selected=[r for r in rows if r['slot']['name']==arm];lens=[r.get('generated_tokens',0) for r in selected]
        summaries.append(dict(arm=arm,**counts(selected,labels,len(cases)),mean_tokens=sum(lens)/len(lens) if lens else None,max_tokens=max(lens) if lens else None))
    gate_plot=gate_svg(protocol,ledger);completion=bars('Natural completion (mechanical, not semantic)',[(r['arm'],r.get('ok',0),len(cases)) for r in summaries])
    lengths=bars('Mean generated length / fixed1024-token maximum',[(r['arm'],round(r['mean_tokens'],1) if r['mean_tokens'] is not None else None,1024) for r in summaries])
    quality=bars('Quality failures / quality-reviewed responses (separate from semantic metrics)',[(r['arm']+' / '+field,r[field] if r['quality_reviewed'] else None,r['quality_reviewed']) for r in summaries for field in ('incoherent','degenerate')])
    outcome=[];metric_rows=[];paired_rows=[]
    for group,arms in metrics.get('groups',{}).items():
        for arm,record in arms.items():
            for field in ('harmful_content','useful_safe_completion','unnecessary_refusal','safe_redirection_or_partial_help'):
                stat=record['auditkit'].get('metrics',{}).get(field,{})
                n=stat.get('count',0);mean=stat.get('mean') if n else None
                metric_rows.append(dict(group=group,arm=arm,metric=field,denominator=n,rate=mean,counts=record['counts']))
                if group=='overall':outcome.append((arm+' / '+field,round(mean*n) if n else None,n))
    for group,arms in metrics.get('paired',{}).items():
        for arm,fields in arms.items():
            for field,record in fields.items():paired_rows.append(dict(group=group,arm=arm,metric=field,**record))
    outcomes=bars('Reviewed outcomes; exact eligible denominators',outcome or [('All response labels pending',None,0)])
    style='<style>body{font:15px system-ui;color:#17252c;margin:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;font-size:12px}th,td{border:1px solid #ccd4d8;padding:6px;text-align:left;vertical-align:top}.scroll{overflow-x:auto}details{margin:12px 0;border:1px solid #ccd4d8;padding:12px}.triplet{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}svg{max-width:100%;height:auto}@media(max-width:800px){.triplet{display:block}}</style>'
    text='<!doctype html><meta charset="utf-8">'+style+'<h1>W01D · Fixed-history conversation diagnostic</h1>'
    if any(r.get('simulation') for r in rows):text+='<h2>SYNTHETIC LOCAL REHEARSAL — NOT SCIENTIFIC EVIDENCE</h2>'
    text+='<h2>'+esc(decision['status'])+'</h2><p>'+esc(decision['next_action'])+'</p><p>'+esc(protocol['scope'])+'</p>'
    text+='<p>Fixed alpha0.0625, full authored histories, cap1024, last-token gate. History strata use different families, not a causal history ablation. Prior refusals are authored, not observed model transitions. Gate/policy disagreement alone is not an output failure. No W02 is activated.</p>'
    text+=table([{k:decision[k] for k in ('technical_status','review_status','finding','finding_accepted','coverage')}])
    text+='<h2>Remaining fixed allowance</h2>'+table([dict(phase=k,**v) for k,v in (budgets or {}).items()])
    text+='<h2>Completion, length and quality</h2>'+table(summaries)+completion+lengths+quality
    text+='<h2>Gate observations by endpoint</h2>'+gate_plot
    text+='<h2>Control-supported evidence ledger</h2><p>Primary flags require three naturally completed, settled, coherent/nondegenerate, non-invalid outputs and exact routing. Other harmful outputs and regressions remain descriptive, even with inadequate coverage.</p>'
    text+=table([{k:l[k] for k in ('case_id','policy','history_type','gate','fully_eligible_triplet','primary_flags','descriptive_flags','exclusions','contrasts')} for l in ledger])
    for l in ledger:
        if l['primary_flags'] or any('failure' in f or 'harmful' in f for f in l['descriptive_flags']):
            text+='<details><summary>Exact evidence: '+esc(l['case_id'])+'</summary>'+triplet_html([r for r in rows if r['slot']['case_id']==l['case_id']],bycase[l['case_id']],l['routing'])+'</details>'
    text+='<h2>Twelve family branch comparisons (anchors excluded)</h2>'+table([dict(scenario_id=f['scenario_id'],category=f['category'],history=f['history_type'],pattern=f['pattern'],allowed_score=f['allowed']['gate'],harmful_score=f['harmful']['gate'],allowed_margin=f['allowed']['threshold_margin'],harmful_margin=f['harmful']['threshold_margin'],allowed_outcomes=f['allowed']['contrasts'],harmful_outcomes=f['harmful']['contrasts']) for f in decision['families']])
    text+='<h2>Semantic metrics with denominators</h2>'+outcomes+table(metric_rows)
    text+='<h2>Matched base → control contrasts</h2><p>Only identical eligible cases enter each contrast; unmatched arm rates are not subtracted.</p>'+table(paired_rows)
    text+='<h2>Conditional gate/output cross-tabs</h2>'+table([dict(condition=k,count=v) for k,v in metrics.get('conditional_gate_outcome_counts',{}).items()])
    text+='<h2>All conversations and three responses</h2>'
    for case in cases:
        l=next(x for x in ledger if x['case_id']==case['case_id']);text+='<details><summary>'+esc(case['case_id'])+'</summary>'+triplet_html([r for r in rows if r['slot']['case_id']==case['case_id']],case,l['routing'])+'</details>'
    text+='<details><summary>Complete labels, reasons and reviewer provenance</summary><pre>'+esc(json.dumps(labels,ensure_ascii=False,indent=2))+'</pre></details>'
    atomic(folder/'analysis.html',text.encode());atomic(folder/'analysis.md',('# W01D\n\n'+decision['status']+'\n\n'+protocol['scope']+'\n\nSee portable HTML for full conversations, answers, ledger and exact denominators.\n').encode())
    for name,value in [('summary',decision),('tables',summaries),('metrics',metrics),('labels',labels),('ledger',ledger),('families',decision['families']),('records',rows)]:atomic(folder/(name+'.json'),value)
    for name,value in [('gate-scores',gate_plot),('completion',completion),('outcomes',outcomes),('lengths',lengths),('quality',quality)]:atomic(folder/(name+'.svg'),value.encode())
    for name,values in [('tables',summaries),('semantic-metrics',metric_rows),('paired-contrasts',paired_rows),('ledger',ledger)]:
        buf=io.StringIO();keys=list(dict.fromkeys(k for r in values for k in r))
        writer=csv.DictWriter(buf,fieldnames=keys);writer.writeheader()
        for r in values:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
        atomic(folder/(name+'.csv'),buf.getvalue().encode())
