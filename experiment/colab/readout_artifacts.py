"""Immutable W02 receipts and portable, independently verifiable snapshots."""
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import conversation_state as st
from conversation_artifacts import inventory, receipt

PHASES=('calibrate','compare','verify')
STAGES=(*PHASES,'final','disposition')


def publish(ns,stage,data):
    result=dict(data,stage=stage,files=inventory(ns))
    identity=st.digest(result)
    st.immutable(ns/'receipts'/(identity+'.json'),result)
    st.atomic(ns/'pointers'/(stage+'.json'),dict(sha256=identity))
    if stage in PHASES and data['status']=='complete':
        st.immutable(ns/'pointers'/(stage+'-complete.json'),dict(sha256=identity))
    return identity


def pack(ns, files, extra, name, identity):
    index=dict(files=files.copy())
    index.update(outer_sha256=identity) if name!='unpublished-recovery' else index.update(unpublished=True,snapshot_sha256=identity)
    paths={n:ns/n for n in files}
    for n,data in extra.items():
        index['files'][n]=st.sha(data)
    out=ns/'exports'/(name+'-'+identity+'.zip')
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix('.'+uuid4().hex+'.partial')
    try:
        with ZipFile(tmp,'w') as z:
            for n,h in sorted(index['files'].items()):
                raw=extra[n] if n in extra else paths[n].read_bytes()
                st.require(st.sha(raw)==h,'Artifact changed during export '+n)
                z.writestr(ZipInfo(n),raw,compress_type=ZIP_DEFLATED)
            z.writestr(ZipInfo('INDEX.json'),st.encoded(index),compress_type=ZIP_DEFLATED)
        with ZipFile(tmp) as z:
            st.require(set(z.namelist())==set(index['files'])|{'INDEX.json'} and z.read('INDEX.json')==st.encoded(index),'Wrong ZIP inventory')
            for n,h in index['files'].items():
                st.require(st.sha(z.read(n))==h,'ZIP readback mismatch')
        if out.exists():
            st.require(out.read_bytes()==tmp.read_bytes(),'Conflicting existing export')
        else:
            tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return dict(path=str(out),zip_sha256=st.sha(out.read_bytes()),**{('snapshot_sha256' if name=='unpublished-recovery' else 'receipt_sha256'):identity})


def export(ns,stage,identity=None):
    st.require(stage in STAGES,'Invalid export stage')
    identity=identity or st.read(ns/'pointers'/(stage+'.json'))['sha256']
    r=receipt(ns,identity)
    st.require(r['stage']==stage,'Wrong export phase')
    extra={'outer-receipt.json':st.encoded(r)}
    p=r['parent']
    while (ns/'receipts'/(p+'.json')).is_file():
        name='parent-receipts/'+p+'.json'
        st.require(name not in extra,'Cyclic parent receipts')
        prior=receipt(ns,p)
        extra[name]=st.encoded(prior)
        p=prior['parent']
    return pack(ns,r['files'],extra,'w02-'+stage,identity)


def recover(ns):
    files=inventory(ns)
    st.require(files,'No saved W02 evidence')
    # Ignore active attempt logs which may still grow; never manufacture a stage receipt.
    files={k:v for k,v in files.items() if not k.endswith(('.log','.partial'))}
    report=dict(status='unpublished_recovery_snapshot',files=files,ancestry_eligible=False)
    identity=st.digest(report)
    return pack(ns,files,{'recovery.json':st.encoded(report)},'unpublished-recovery',identity)
