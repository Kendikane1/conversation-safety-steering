"""Admit either the canonical Drive receipt tree or its retrieved W01D export."""
from pathlib import Path
import conversation_state as st
import conversation_model
import conversation_review as review
from readout_science import positions


def admit(root, protocol, archive=False):
    expected = protocol['w01d']
    receipts = {}
    for stage in ('final','review','diagnose'):
        identity = expected[stage]
        path = (root/'outer-receipt.json' if stage=='final' else root/'parent-receipts'/(identity+'.json')) if archive else root/'receipts'/(identity+'.json')
        st.require(st.sha(path.read_bytes())==identity, 'Wrong W01D '+stage+' receipt')
        receipt = st.read(path)
        st.require(receipt['stage']==stage and receipt['status']=='complete' and receipt['bundle']==expected['package'], 'Unaccepted W01D parent')
        receipts[stage] = receipt
    final, reviewed, diagnosed = (receipts[k] for k in ('final','review','diagnose'))
    for name, identity in final['files'].items():
        st.require(not Path(name).is_absolute() and '..' not in Path(name).parts and st.sha((root/name).read_bytes())==identity, 'Changed W01D file '+name)
    old = st.read(root/'inputs/w01_conversation_v1.json')
    st.require(final['parent']==expected['review'] and reviewed['parent']==expected['diagnose'] and diagnosed['parent']==old['parent_final'], 'Broken ancestry')
    st.require(all(old[k]==protocol[k] for k in ('condition','behavior_layers','generation','seed','vectors_sha256','calibration_checkpoint')), 'Fixed protocol drift')
    st.require(st.sha((root/'inputs/w01_diagnostic.jsonl').read_bytes())==protocol['fixtures']['w01_diagnostic.jsonl'], 'Wrong diagnostics')
    imported = root/reviewed['labels_path']
    st.require(st.sha(imported.read_bytes())==expected['labels'], 'Wrong accepted labels')
    envelope = st.read(imported)
    folder = (root/final['analysis_path']).parent
    rows = st.read(folder/'records.json')
    st.require(envelope==st.read(root/final['labels_path']) and envelope['labels']==st.read(folder/'labels.json'), 'Final label drift')
    st.require(rows==st.read((root/diagnosed['review_template_path']).parent/'records.json'), 'Final source records differ')
    review.validate(envelope,st.read(root/diagnosed['review_template_path']),rows)
    joined = review.joins(rows,envelope['labels'])
    st.require(len(joined)==len(rows)==96 and all(review.eligible(r,l) and l['quality_status']=='reviewed' for r,l in joined.values()), 'Incomplete accepted records')
    maps = {}
    for cid in old['case_order']:
        row = next(r for r in rows if r['case_id']==cid and r['slot']['name']=='conditional')
        check = conversation_model.routing_check(row,rows)
        st.require(check['equal'] and check==st.read(root/'science/diagnose/routing'/(row['slot']['slot_id']+'.json')), 'Changed control routing '+cid)
        maps[cid] = positions(row['messages'],row)
        for arm in ('base','always_on'):
            control,label = joined[cid,arm]
            if control['response']==row['response']:
                consistent(label,joined[cid,'conditional'][1])
    st.require(len(maps)==32 and final['decision']['status']=='gate_related_failure_observed', 'Wrong diagnostic disposition')
    return dict(joined=joined, maps=maps, rows=rows, envelope=envelope, metrics=st.read(folder/'metrics.json'),
                decision=final['decision'], receipts={k:expected[k] for k in receipts})


def consistent(left,right):
    if left['status']==right['status']=='reviewed':
        st.require(all(left[k]==right[k] for k in review.FIELDS), 'Conflicting identical-answer judgments on '+left['case_id']+'; central adjudication required')
    if left['quality_status']==right['quality_status']=='reviewed':
        st.require(all(left[k]==right[k] for k in ('coherent','degenerate_repetition')), 'Identical-answer quality conflict')
