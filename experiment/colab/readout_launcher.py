"""Colab operator interface. One explicitly selected stage per invocation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import conversation_state as st
import readout_artifacts as artifacts


PRIVATE=Path('./private-runtime-example')


def run(stage,bundle):
    from google.colab import files
    from IPython.display import HTML,display
    private=PRIVATE
    ns=private/'readout-results'/bundle
    job=dict(stage=stage,bundle=bundle,private=str(private),labels='',label_filename='',parent='',reference='')
    if stage not in ('recover','export'):
        ref=input('Enter '+stage+' followed by the central reference. Blank stops. ').strip()
        st.require(ref.startswith(stage+' ') and ref[len(stage):].strip(),'Stopped before action')
        job['reference']=ref
    if stage=='export':
        job['parent']=input('Published stage to retrieve (calibrate/compare/verify/final/disposition): ').strip()
    elif stage=='disposition':
        job['parent']=input('Interrupted phase: ').strip()
        job['slot']=input('Exact unfinished slot ID to abandon: ').strip()
    elif stage=='calibrate':
        job['parent']=st.read(HERE/'w02_readout_v1.json')['w01d']['final']
    elif stage in ('compare','verify','final'):
        parents={'compare':['calibrate'],'verify':['compare'],'final':['verify','compare']}
        default=''
        for phase in parents[stage]:
            ptr=ns/'pointers'/(phase+'.json')
            if ptr.exists():
                default=st.read(ptr)['sha256']
                artifacts.receipt(ns,default)
                break
        print('Verified default parent',default or 'none')
        job['parent']=input('Parent outer receipt SHA (Enter for displayed default): ').strip() or default
        prior=artifacts.receipt(ns,job['parent'])
        if stage=='final' and prior['stage']=='verify' and prior['status']=='complete':
            choice=input('Enter import for one filled NEW verify envelope, or preview for pending-only analysis: ').strip()
            st.require(choice in ('import','preview'),'Explicit label choice required')
            if choice=='preview':
                job['labels']='PREVIEW'
            else:
                uploaded=files.upload()
                st.require(len(uploaded)==1,'Exactly one filled NEW verify review envelope is required')
                filename,raw=next(iter(uploaded.items()))
                labels=json.loads(raw)['labels']
                print(filename,st.sha(raw),'settled semantic',sum(r['status']=='reviewed' for r in labels),'settled quality',sum(r['quality_status']=='reviewed' for r in labels))
                path=private/'readout-label-imports'/(st.sha(raw)+'.json')
                st.immutable(path,raw)
                job.update(labels=str(path),label_filename=Path(filename).name)
    print('Stage',stage,'parent',job['parent'],flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        request=Path(tmp)/'job.json'
        st.immutable(request,job)
        cmd=[sys.executable,'-I','-B','-u',str(HERE/'readout_runner.py'),'controller',str(request)]
        exported=None
        with subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) as proc:
            try:
                for line in proc.stdout:
                    if not line.startswith('W02_EVENT '):
                        print(line,end='',flush=True)
                        continue
                    event=json.loads(line[len('W02_EVENT '):])
                    kind,data=event['kind'],event['data']
                    if kind=='observation':
                        display(HTML(data['html']))
                    elif kind=='analysis':
                        path=Path(data['path'])
                        st.require(path.is_relative_to(ns) and st.sha(path.read_bytes())==data['sha256'],'Unverified report path')
                        display(HTML(path.read_text()))
                    elif kind=='export':
                        exported=data
                    else:
                        print(kind,data,flush=True)
                code=proc.wait()
            finally:
                if proc.poll() is None:
                    proc.terminate()
        st.require(code==0 and exported,'Stage stopped before export. Use Recover for unpublished slots.')
        path=Path(exported['path'])
        st.require(path.is_relative_to(ns/'exports') and st.sha(path.read_bytes())==exported['zip_sha256'],'Download identity mismatch')
        print(exported,flush=True)
        files.download(str(path))
        print('Return the downloaded ZIP and both identities for central review. Stop here.')
