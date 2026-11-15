"""Complete, verified W01D review exports, including partial attempts."""
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
import conversation_state as st


def inventory(namespace):
    files={}
    for directory in ('inputs','parents','science','analysis','attempts'):
        for path in sorted((namespace/directory).rglob('*')):
            if not path.is_file() or path.name=='checkpoint-current.json':continue
            st.require(not path.is_symlink(),'Symlink in review evidence')
            name=str(path.relative_to(namespace))
            st.require(path.suffix not in ('.pt','.safetensors','.whl','.zip'),'Model/cache/package excluded from review ZIP')
            files[name]=st.sha(path.read_bytes())
    return files


def publish(namespace,stage,report):
    files=inventory(namespace)
    receipt=dict(report,stage=stage,files=files)
    digest=st.digest(receipt)
    st.immutable(namespace/'receipts'/(digest+'.json'),receipt)
    st.atomic(namespace/'pointers'/(stage+'.json'),{'sha256':digest})
    if report['status']=='complete':
        (st.immutable if stage in ('diagnose',) else st.atomic)(namespace/'pointers'/(stage+'-complete.json'),{'sha256':digest})
    return digest,receipt


def receipt(namespace,digest):
    st.require(len(digest)==64 and all(c in '0123456789abcdef' for c in digest),'Invalid receipt SHA')
    path=namespace/'receipts'/(digest+'.json')
    st.require(st.sha(path.read_bytes())==digest,'Receipt SHA mismatch')
    data=st.read(path)
    for name,h in data['files'].items():
        p=namespace/name
        st.require(not Path(name).is_absolute() and '..' not in Path(name).parts and not p.is_symlink(),'Unsafe artifact path')
        st.require(st.sha(p.read_bytes())==h,'Artifact changed: '+name)
    return data


def export(namespace,stage,completed_only=False):
    st.require(stage in ('diagnose','review','final','disposition'),'Invalid export stage')
    pointer=namespace/'pointers'/(stage+('-complete' if completed_only else '')+'.json')
    digest=st.read(pointer)['sha256'];data=receipt(namespace,digest)
    files={name:(namespace/name).read_bytes() for name in data['files']}
    files['outer-receipt.json']=(namespace/'receipts'/(digest+'.json')).read_bytes()
    parent=data.get('parent');seen=set()
    while isinstance(parent,str) and len(parent)==64 and (namespace/'receipts'/(parent+'.json')).is_file():
        st.require(parent not in seen,'Cyclic receipt ancestry');seen.add(parent)
        prior=receipt(namespace,parent)
        files['parent-receipts/'+parent+'.json']=(namespace/'receipts'/(parent+'.json')).read_bytes()
        parent=prior.get('parent')
    # A separate arm-hidden review set is included; never claim the whole bundle is blinded.
    index={name:st.sha(raw) for name,raw in files.items()}
    files['INDEX.json']=st.encoded({'schema':1,'outer_sha256':digest,'files':index})
    out=namespace/'exports'/f'w01d-{stage}-{digest}.zip';out.parent.mkdir(exist_ok=True)
    tmp=out.with_suffix('.partial')
    with ZipFile(tmp,'w') as archive:
        for name,raw in sorted(files.items()):archive.writestr(ZipInfo(name),raw,compress_type=ZIP_DEFLATED)
    with ZipFile(tmp) as archive:
        st.require(set(archive.namelist())==set(files),'Export member mismatch')
        for name,raw in files.items():st.require(archive.read(name)==raw,'Export readback mismatch')
    if out.exists():
        st.require(out.read_bytes()==tmp.read_bytes(),'Existing export differs');tmp.unlink()
    else:tmp.replace(out)
    return dict(path=str(out),sha256=st.sha(out.read_bytes()),members=len(files),receipt_sha256=digest,
                backup_status='Verified archive readback; browser/local download not independently verified')
