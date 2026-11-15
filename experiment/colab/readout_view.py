"""Portable notebook research displays; escape all authored and generated content."""
import csv
import io
import json
from html import escape
from conversation_state import immutable


def esc(value):
    return escape(str(value))


def table(rows):
    if not rows:
        return '<p>No observations.</p>'
    keys=list(rows[0])
    return '<table><thead><tr>'+''.join('<th>'+esc(k)+'</th>' for k in keys)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+esc(row.get(k,''))+'</td>' for k in keys)+'</tr>' for row in rows)+'</tbody></table>'


def observation(row, cutoffs=None):
    from readout_science import ARMS, DEPLOYED
    if 'scores' not in row or 'proof' not in row:
        return '<pre>'+esc(row)+'</pre>'
    proof=row['proof']
    parts=['<h3>'+esc(row['case_id'])+'</h3>']
    for span in proof['spans']:
        token=span['last_text']
        content=span['content']
        line=esc(content)
        if token and content.endswith(token):
            line=esc(content[:-len(token)])+'<mark>'+esc(token)+'</mark>'
        arms=[a for a,ix in proof['indices'].items() if span['last'] in ix]
        parts.append('<p><b>'+esc(span['role'])+'</b> '+line+' <small>'+esc(', '.join(arms))+' · index '+str(span['last'])+'</small></p>')
    parts.append(table([dict(readout=a,indices=ix,ids=[proof['input_ids'][i] for i in ix],
                             users=sum(s['role']=='user' and s['last'] in ix for s in proof['spans']),
                             assistants=sum(s['role']=='assistant' and s['last'] in ix for s in proof['spans']),
                             selected='generation prefix <|START_RESPONSE|>' if a=='B' else [s['last_text'] or '(token text awaits live offsets)' for s in proof['spans'] if s['last'] in ix],
                             threshold=scheme,score=format(row['scores'][a],'.8f'),cutoff=format(t,'.8f'),margin=format(row['scores'][a]-t,'+.8f'),open=row['scores'][a]>t)
                        for a in ARMS for ix in [proof['indices'][a]] for scheme,t in ([('common',DEPLOYED),('calibrated',cutoffs[a])] if cutoffs else [('common',DEPLOYED)])]))
    if 'response' in row:
        parts.extend(['<h4>Fresh live answer</h4><pre>'+esc(row['response'])+'</pre>',
                      '<h4>Selected W01D control</h4><pre>'+esc(row.get('control_response',''))+'</pre>'])
    return ''.join(parts)


def save(folder,stage,rows,report):
    header='<!doctype html><meta charset="utf-8"><style>body{font:16px system-ui;max-width:1150px;margin:2em auto}pre,td{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse}th,td{padding:.4em;border:1px solid #bbb}mark{background:#ffe897}details{margin:1em 0}</style>'
    html=[header,'<h1>W02 '+esc(stage)+'</h1>']
    csv_rows=[]
    replay=report.get('replay',{})
    frozen=report.get('frozen',{})
    if frozen:
        html.append('<h2>Frozen nomination · '+esc(frozen['nominee'])+'</h2>'+table(list(frozen['nomination'].values())+[dict(frozen['deployed_B'],arm='deployed B')]))
        html.append('<details><summary>Threshold fitting · 804 grid points</summary>'+table([r for grid in frozen['grid'].values() for r in grid])+'</details>')
    for k in ('disposition','decision','failed_phase','error','errors','technical_status','review_status','next_action','replay_effect','live_verification','baseline_disposition','live_metrics','live_paired','budgets'):
        if k in report:
            html.append('<h2>'+esc(k.replace('_',' '))+'</h2><pre>'+esc(json.dumps(report[k],indent=1))+'</pre>')
    for row in rows:
        html.append('<details><summary>'+esc(row.get('case_id',row.get('slot',{}).get('case_id','slot')))+'</summary>'+observation(row,frozen.get('thresholds'))+'</details>')
    if replay:
        html.append('<h2>Measured gates and routing replay</h2><p>Maximum absolute stock B error '+esc(replay['max_B_error'])+'</p>')
        html.append('<details><summary>Prespecified position contrasts</summary><pre>'+esc(json.dumps(replay['position_contrasts'],indent=1))+'</pre></details>')
        for name,view in replay['views'].items():
            html.append('<h3>'+esc(name)+'</h3>'+table([dict(group=k,**v['counts'],coverage=v['quality'],gate=v['gate_confusion']) for k,v in replay['metrics'][name].items()]))
            html.append('<pre>'+esc(json.dumps(dict(paired=replay['paired'][name],reference_coverage=replay['reference_coverage'][name]),indent=1))+'</pre>')
            for r in view:
                csv_rows.append({k:r[k] for k in ('case_id','kind','category','policy','route','score','cutoff','margin','open','view_id','response_sha256','source_record_sha256')}|dict(view=name,label_id=r['label']['review_id']))
        for i,r in enumerate(replay['views']['common-B']):
            html.append('<details><summary>'+esc(r['case_id'])+' · compare replay answers</summary>'+table([dict(view=k,route=v[i]['route'],gate=v[i]['open'], margin=v[i]['margin'],answer=v[i]['record']['response'],reason=v[i]['label']['reason']) for k,v in replay['views'].items()])+'</details>')
        dots=[]
        for j,(family,_) in enumerate(replay['families']['common-B'].items()):
            y=30+j*32
            dots.append(f'<text x="5" y="{y}">{esc(family)}</text>')
            for n,(name,color) in enumerate(zip(('common-B','common-L','common-U','common-D'),('#222','#c64522','#0477a2','#604aab'))):
                subset=[r for r in replay['views'][name] if r['scenario_id']==family]
                a,b=[220+160*r['score'] for r in subset]
                dots.append(f'<line x1="{a}" x2="{b}" y1="{y+n*3}" y2="{y+n*3}" stroke="{color}"/><circle cx="{a}" cy="{y+n*3}" r="3" fill="white" stroke="{color}"/><circle cx="{b}" cy="{y+n*3}" r="3" fill="{color}"/>')
        svg='<svg xmlns="http://www.w3.org/2000/svg" width="510" height="420"><title>Family score pairs. Hollow allowed, filled harmful. B black, L orange, U blue, D purple. Scores from -1 to 1.</title>'+''.join(dots)+'<text x="60" y="415">−1</text><text x="216" y="415">0</text><text x="377" y="415">1</text></svg>'
        immutable(folder/'family-scores.svg',svg.encode())
        html.append('<h2>Within-family scores</h2><p>Hollow marker, allowed. Filled marker, harmful. B black, L orange, U blue, D purple.</p>'+svg)
    if report.get('live'):
        html.append('<h2>Fresh review decisions</h2>'+table([dict(case_id=r['case_id'],status=(r['label'] or {}).get('status','pending'),
            review_id=r['view_id'],reason=(r['label'] or {}).get('reason',''),response=r['record']['response']) for r in report['live']]))
    if csv_rows:
        buffer=io.StringIO()
        writer=csv.DictWriter(buffer,fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
        immutable(folder/'views.csv',buffer.getvalue().encode())
    immutable(folder/'report.json',report)
    immutable(folder/'analysis.html',''.join(html).encode())
