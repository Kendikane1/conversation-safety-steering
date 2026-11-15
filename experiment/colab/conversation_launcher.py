"""Classic Colab notebook entry and streaming renderer; no scientific-stack imports."""
from pathlib import Path
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import traceback
from uuid import uuid4

HERE=Path(__file__).resolve().parent
PRIVATE=Path('./private-runtime-example')
sys.path.insert(0,str(HERE))
from conversation_state import require,read,sha
from conversation_view import response_html,table,esc


def run(stage,bundle):
    from google.colab import drive,files
    from IPython.display import display,HTML
    private=PRIVATE
    drive.mount('/content/drive')
    from conversation_artifacts import receipt
    ns=private/'conversation-results'/bundle
    if stage=='export':
        parent=input('Export which stage: diagnose/review/final/disposition? ').strip()
        review='';labels='';slot=''
    else:
        review=input(f'Enter "{stage} <central clearance or analysis reference>" (blank stops): ').strip()
        require(review.startswith(stage+' ') and review[len(stage):].strip(),'Stopped before action')
        if stage=='diagnose':parent=read(HERE/'w01_conversation_v1.json')['parent_final']
        elif stage=='disposition':parent=input('Interrupted phase (diagnose): ').strip()
        else:
            previous={'review':'diagnose','final':'review'}[stage]
            pointer=ns/'pointers'/(previous+'.json');default=read(pointer)['sha256'] if pointer.exists() else ''
            if default:receipt(ns,default)
            print('Verified default parent:',default or 'none; supply reviewed outer SHA',flush=True)
            parent=input('Parent outer SHA (Enter accepts displayed default): ').strip() or default
            require(bool(parent),'No parent selected')
        print('Selected parent:',parent,flush=True)
        slot=input('Exact interrupted slot ID to abandon WITHOUT RETRY: ').strip() if stage=='disposition' else ''
        labels=''
        needs_labels=stage=='review'
        if needs_labels:
            choice=input('Choose import (filled new label JSON) or preview (PENDING ONLY, no decision): ').strip().lower()
            require(choice in ('import','preview'),'Choose literal import or preview; omitted labels are not completed review')
            if choice=='preview':
                labels='PREVIEW';print('PENDING-ONLY PREVIEW: no reviewed decision is ready.',flush=True)
            else:
                uploaded=files.upload();require(len(uploaded)==1,'Upload exactly one filled NEW label JSON')
                filename,raw=next(iter(uploaded.items()));data=json.loads(raw)
                print('Uploaded:',filename,'SHA-256:',sha(raw),'Quality reviewed:',sum(r.get('quality_status')=='reviewed' for r in data['labels']),
                      'Semantic reviewed:',sum(r.get('status')=='reviewed' for r in data['labels']),
                      'Capped exclusions:',sum(r.get('finish_status')=='truncated' for r in data['labels']),flush=True)
                path=private/'conversation-label-imports'/(sha(raw)+'.json');path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():require(path.read_bytes()==raw,'Existing label hash conflict')
                else:path.write_bytes(raw)
                labels=str(path)
    print(f'Starting W01D {stage}; progress and completed responses will appear below. Do not click twice.',flush=True)
    command=[sys.executable,'-I','-B','-u',str(HERE/'conversation_runner.py'),'controller',stage,review,parent,bundle,labels,slot]
    exports=[];last_status=None;transcript=[];interrupted=False
    proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    def render(line):
        nonlocal last_status
        transcript.append(line)
        if not line.startswith('W01D_EVENT '):print(line,end='',flush=True);return
        event=json.loads(line[len('W01D_EVENT '):]);kind,data=event['kind'],event['data']
        if kind=='response':
            require(sha((json.dumps(data['record'],sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode())==data['record_sha256'],
                    'Displayed response hash differs from committed record')
            display(HTML(response_html(data['record'],data['case'])))
            print('Budget:',json.dumps(data['budget']),flush=True)
        elif kind=='triplet':
            from conversation_view import triplet_html
            from conversation_state import digest
            require(all(digest(r)==data['record_hashes'][r['slot']['slot_id']] for r in data['records']),'Displayed triplet differs from committed records')
            display(HTML(triplet_html(data['records'],data['case'],data['routing'])))
        elif kind=='analysis':
            path=Path(data['path']);require(path.is_relative_to(private/'conversation-results'/bundle),'Foreign analysis path')
            raw=path.read_bytes();require(sha(raw)==data['sha256'],'Analysis view hash mismatch');display(HTML(raw.decode()))
        elif kind=='export':
            exports.append(data);print('Verified review ZIP:',data['path'],'SHA-256',data['sha256'],flush=True)
        elif kind=='receipt':
            last_status=data['status'];print('W01D receipt:',json.dumps(data),flush=True)
        elif kind in ('readiness','admission_ok','model_ready','decision','failure','routing','tokenization','setup','label_import','cleanup'):
            display(HTML('<h3>'+esc(kind)+'</h3><pre>'+esc(json.dumps(data,ensure_ascii=False,indent=2))+'</pre>'))
        else:print(kind,json.dumps(data,ensure_ascii=False),flush=True)
    try:
        try:
            for line in proc.stdout:render(line)
        except KeyboardInterrupt:
            interrupted=True
            # Interrupt only this controller; it stops its own worker and exports partial evidence.
            proc.send_signal(signal.SIGTERM)
            for line in proc.stdout:render(line)
        code=proc.wait()
        for item in exports:
            path=Path(item['path']);require(path.is_relative_to(private/'conversation-results'/bundle),'Foreign export path')
            require(sha(path.read_bytes())==item['sha256'],'ZIP changed before download')
            files.download(str(path))
        print(f'W01D {stage} stopped. Return the review ZIP and SHA to central; no next stage is automatically cleared.',flush=True)
        require(code==0 and last_status not in ('failed',) and not interrupted,'Stage failed/interrupted; preserve partial export and review before retry')
    except BaseException:
        if proc.poll() is None:proc.send_signal(signal.SIGTERM)
        fallback=Path(tempfile.gettempdir())/('w01d-launcher-'+uuid4().hex+'.json')
        raw=json.dumps({'stage':stage,'parent':parent,'bundle':bundle,'status':'launcher_failure',
                        'traceback':traceback.format_exc(),'last_output':transcript[-30:]},ensure_ascii=False).encode()
        fallback.write_bytes(raw)
        print('Launcher failure receipt:',fallback,'SHA-256',sha(raw),'Download before reset.',flush=True)
        files.download(str(fallback))
        raise
