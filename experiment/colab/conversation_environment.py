"""Narrow adoption of accepted v4 evidence; immutable parent code is kept separate."""
from pathlib import Path
import json
import sys
import gpu_runner as gpu
import conversation_state as st

HERE=Path(__file__).resolve().parent


def inputs():
    manifest=st.read(HERE/'conversation_manifest.json')
    for name,h in manifest['files'].items():
        st.require(st.sha((HERE/name).read_bytes())==h,'Changed packaged input: '+name)
    protocol=st.read(HERE/'w01_conversation_v1.json')
    return protocol,manifest


def adopt(private,protocol):
    import length_environment as inherited
    import length_artifacts as archive
    import length_state as state
    import length_model as model
    import length_compare as comparisons
    old_protocol=st.read(HERE/'w01_length_v1.json')
    st.require(st.sha((HERE/'w01_length_v1.json').read_bytes())==protocol['parent_length_protocol'],'W01L protocol differs')
    adopted=inherited.adopt(private,old_protocol)
    ns=private/'length-results'/protocol['parent_length_package']
    names={'final':'parent_final','confirm':'parent_confirmation','select':'parent_selection','compare':'parent_comparison'}
    receipts={phase:archive.receipt(ns,protocol[key]) for phase,key in names.items()}
    for phase,r in receipts.items():
        st.require(r['stage']==phase and r['status']=='complete' and r['bundle']==protocol['parent_length_package'],'Wrong accepted W01L '+phase)
    for phase,parent in [('final','confirm'),('confirm','select'),('select','compare')]:
        st.require(receipts[phase]['parent']==protocol[names[parent]],'Wrong W01L ancestry')
    st.require(receipts['compare']['parent']==old_protocol['parent_final'],'W01S ancestor differs')
    st.require(st.sha((ns/'inputs/w01_length_v1.json').read_bytes())==protocol['parent_length_protocol'],'Saved W01L protocol differs')
    selection=st.read(ns/receipts['select']['selection_path'])
    st.require(selection['status']=='selected' and selection['alpha']==.0625 and selection['arm']=='alpha_0.0625','Accepted strength differs')
    final=receipts['final']
    st.require(final['decision']['status']=='baseline_candidate_for_later_diagnostic' and final['decision']['alpha']==.0625,'W01L final not accepted candidate')
    compare_labels=st.read(ns/receipts['select']['labels_path'])
    st.require(st.sha((ns/receipts['select']['labels_path']).read_bytes())==protocol['parent_comparison_labels']==selection['labels_sha256'],'W01L comparison labels differ')
    raw=(HERE/'W01L_CONFIRM_LABELS.json').read_bytes()
    st.require(st.sha(raw)==protocol['parent_confirmation_labels'],'Packaged accepted confirmation labels differ')
    st.require(final['label_import']['sha256']==protocol['parent_confirmation_labels'],'W01L final imported different confirmation labels')
    confirmation_labels=st.read(HERE/'W01L_CONFIRM_LABELS.json')
    prior_upload=private/'length-label-imports'/(protocol['parent_confirmation_labels']+'.json')
    if prior_upload.exists():st.require(prior_upload.read_bytes()==raw,'Saved confirmation upload differs')
    combined=st.read(ns/Path(final['analysis_path']).parent/'labels.json')
    st.require(combined==compare_labels['labels']+confirmation_labels['labels'],'W01L combined labels differ')
    cohorts={}
    for phase,count in [('compare',32),('confirm',16)]:
        store=state.Store(ns/'science'/phase,st.read(ns/'science'/phase/'plan.json'));rows=store.records()
        st.require(len(rows)==count and not store.unfinished() and all(r['status']=='ok' for r in rows),'Incomplete W01L cohort')
        st.require(st.read(store.path/'cohort-complete.json')==dict(plan_sha256=store.fingerprint,records_sha256=st.digest(rows)),'W01L completion binding differs')
        st.require(st.read(ns/Path(receipts[phase]['review_template_path']).parent/'records.json')==rows,'W01L review records differ')
        for f in (store.path/'postconditions').glob('*.json'):
            post=st.read(f)
            st.require(all(post[k] for k in ('saved_vectors_unchanged','saved_file_unchanged','parameters_unchanged')) and not post['hooks_after'],'W01L postcondition failure')
        cohorts[phase]=rows
    st.require(comparisons.all_checks(cohorts['compare'],adopted['historical'])['passed'],'W01L old/new comparison failure')
    for r in cohorts['confirm']:
        check=model.routing_check(r,cohorts['compare'],selection)
        st.require(check['equal'] and st.read(ns/'science/confirm/routing'/(r['slot']['slot_id']+'.json'))==check,'W01L routing differs')
    adopted['length_parent']=dict(namespace=str(ns),receipts=receipts,selection=selection,compare_labels=compare_labels,
                                 confirmation_labels=confirmation_labels,records=cohorts,decision=final['decision'])
    for name,h in protocol['preserved_files'].items():
        st.require(st.sha((adopted['root']/name).read_bytes())==h,'W01D scientific input changed: '+name)
    return adopted


def prepare(private,protocol,report,scientific):
    # All inexpensive independent checks precede any install/staging/model work.
    def progress(message):print('W01D_EVENT '+json.dumps({'kind':'setup','data':{'status':message}}),flush=True)
    progress('Checking package, accepted ancestry, frozen host and available resources')
    checks=report['readiness']={}
    package=gpu.check(checks,'package',inputs)
    adopted=gpu.check(checks,'ancestry',lambda:adopt(private,protocol))
    if adopted is not None:checks['ancestry']={'issues':[],'parent':protocol['parent_final'],'project':str(adopted['root'])}
    else:gpu.assert_checks(checks)
    local=gpu.v2.LOCAL/protocol['parent_package']/'cu130';local.mkdir(parents=True,exist_ok=True)
    cache=gpu.v2.LOCAL/gpu.V3/'hub'
    gpu.check(checks,'host',lambda:gpu.runtime.eligibility(gpu.runtime.host(),adopted['wheels']))
    gpu.check(checks,'drive',lambda:gpu.runtime.writable(private/'conversation-results'))
    gpu.check(checks,'local',lambda:gpu.runtime.writable(local))
    if scientific:
        observed=checks.get('host',{}).get('observed',{})
        frozen=adopted['expected_target_host']
        fields=('implementation','version','release','python','platform','system','machine','libc','soabi','debug','free_threaded')
        differences={k:{'expected':frozen[k],'observed':observed.get(k)} for k in fields if frozen[k]!=observed.get(k)}
        checks['frozen_host']={'differences':differences,'issues':['Host differs from accepted GPU lineage'] if differences else []}
        gpu.check(checks,'gpu',gpu.runtime.gpu_cli)
        gpu.check(checks,'resources',lambda:gpu.runtime.storage(private,local,cache,adopted['tree'],
                  st.read(HERE/'gpu_wheel_sizes.json'),(local/'current').exists()))
        durable=adopted['root'].parents[1]/'payloads'
        gpu.check(checks,'payload_presence',lambda:gpu.payload_presence(durable,adopted['tree']))
    gpu.assert_checks(checks)
    # package tuple contains only JSON objects, but no need to duplicate a full inventory.
    checks['package']={'issues':[],'manifest_sha256':st.sha((HERE/'conversation_manifest.json').read_bytes())}
    progress('Verifying existing isolated interpreter, or restoring only the accepted lock')
    env=gpu.clean_environment(local,cache)
    try:
        prefix=gpu.isolated_environment(local,'cu130',adopted['requirements'],env,report)
    except Exception as exc:
        # Only a rejected selected venv is eligible for exact-lock reconstruction.
        # Never delete it or redirect an unrelated environment. Failed fresh installs
        # have no current pointer and are reported without an automatic retry.
        pointer=local/'current'
        if not pointer.is_file():raise
        name=pointer.read_text()
        st.require(name.startswith('venv-') and '/' not in name and '\\' not in name,'Unsafe existing venv pointer')
        report['rejected_environment']={'path':str(local/name),'error':gpu.v2.diagnostic(str(exc)),
                                        'action':'preserved; reconstruct exact lock in a distinct prefix'}
        sizes=st.read(HERE/'gpu_wheel_sizes.json')
        import shutil,tempfile
        allowance=4*sum(v['bytes'] for v in sizes.values())+max(v['bytes'] for v in sizes.values())+1024**3
        free=shutil.disk_usage(local).free
        report['reconstruction_disk']={'required':allowance,'available':free}
        st.require(free>=allowance,'Insufficient disk for isolated reconstruction; existing prefix preserved')
        prefix=Path(tempfile.mkdtemp(prefix='venv-',dir=local))
        gpu.v2.bootstrap(prefix,HERE,report,env)
        gpu.v2.setup_step('reconstruct unchanged GPU lock',gpu.v2.install_args(prefix/'bin/python',adopted['requirements']),report,env)
        report['provisioning']='reconstructed rejected selected venv; original retained'

    progress('Approved isolated environment ready')
    if scientific:
        progress('Verifying/restaging existing offline cache payloads; no model refetch')
        snapshot=gpu.payload.stage_cache(cache,adopted['tree'],adopted['recovery']['trusted_metadata'],
                                        durable,adopted['recovery']['files'])
    else:
        snapshot=None
    progress('Preparation complete; next isolated admission checks precede any generation')
    return adopted,local,prefix,env,snapshot


def worker_admission(job,report,scientific):
    protocol,manifest=inputs()
    adopted=adopt(Path(job['private']),protocol)
    if scientific:
        # Execute the unchanged v4 validation with its original wrapper identity.
        gpu.worker(dict(stage='cu130',root=str(adopted['root']),snapshot=job['snapshot'],
                        tree=adopted['tree'],frozen=adopted['frozen']),report)
    else:
        # Offline manual analysis uses the locked interpreter, never CUDA/model admission.
        report['environment_signature']=gpu.v2.audit_env(adopted['wheels'],adopted['root'],report)
        st.require(report['versions']['pip']=='26.2.2','Unexpected analysis pip')
        report['scope']='offline label/metric analysis; no GPU or model required'
    report['child_protocol_sha256']=st.sha((HERE/'w01_conversation_v1.json').read_bytes())
    report['child_sources']=manifest['files']
    report['parent_sources']=adopted['frozen']['sources']
    return protocol,adopted
