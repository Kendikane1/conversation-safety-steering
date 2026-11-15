"""W01D immutable plans, reserved budgets and per-slot publication; stdlib only."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone


def encoded(value):
    return (json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(encoded(value))


def require(ok,message):
    if not ok:
        raise ValueError(message)


def read(path):
    def unique(pairs):
        d={}
        for k,v in pairs:
            require(k not in d,'Duplicate JSON key: '+k);d[k]=v
        return d
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=data if isinstance(data,bytes) else encoded(data)
    tmp=path.with_name('.'+path.name+'.'+uuid4().hex+'.partial')
    with tmp.open('xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    tmp.replace(path)
    require(path.read_bytes()==raw,'Readback mismatch: '+str(path))
    return sha(raw)


def immutable(path,data):
    path=Path(path);raw=data if isinstance(data,bytes) else encoded(data)
    if path.exists():
        require(path.read_bytes()==raw,'Immutable evidence differs: '+str(path))
    else:
        atomic(path,raw)
    return sha(raw)


def now():
    return datetime.now(timezone.utc).isoformat()


def slots(protocol,phase,selection=None):
    require(phase=='diagnose','Unknown computational phase')
    arms=protocol['arms']
    result=[]
    for index,case in enumerate(protocol['case_order']):
        for arm in arms:
            result.append(dict(slot_id=case+'--'+arm['name'],case_id=case,**arm,
                               max_new_tokens=protocol['generation']['max_new_tokens']))
    return result


class Store:
    """Separate W01D namespace. Claim before work; never retry a consumed slot."""
    def __init__(self,path,plan):
        self.path=Path(path)
        self.plan=plan
        self.fingerprint=immutable(self.path/'plan.json',plan)
        self.by_slot={s['slot_id']:s for s in plan['slots']}
        require(len(self.by_slot)==len(plan['slots']),'Duplicate slot')
        (self.path/'slots').mkdir(exist_ok=True)

    def paths(self,key):
        require(key in self.by_slot,'Unknown slot')
        p=self.path/'slots'/key
        return tuple(p.with_name(p.name+suffix) for suffix in ('.claim.json','.record.json','.commit.json'))

    def records(self):
        rows=[]
        for key in self.by_slot:
            claim,record,commit=self.paths(key)
            if commit.exists():
                meta=read(commit)
                if meta.get('record_file'):
                    expected=record.with_name(key+'.disposition.json')
                    require(meta['record_file']==expected.name,'Invalid disposition record path');record=expected
                require(meta['plan_sha256']==self.fingerprint and claim.exists() and
                        meta['claim_sha256']==sha(claim.read_bytes()) and meta['record_sha256']==sha(record.read_bytes()),'Broken slot commit')
                row=read(record)
                require(row['slot']==self.by_slot[key] and row['plan_sha256']==self.fingerprint,'Slot identity differs')
                require(read(claim)['plan_sha256']==self.fingerprint,'Claim identity differs')
                rows.append(row)
        return rows

    def unfinished(self):
        return [key for key in self.by_slot if self.paths(key)[0].exists() and not self.paths(key)[2].exists()]

    def claim(self,key):
        require(not self.unfinished(),'Started-but-unfinished slot: preserve evidence; explicit central disposition required')
        claim,record,commit=self.paths(key)
        require(not commit.exists() and not record.exists(),'Slot already published or incomplete publication')
        with claim.open('xb') as f:
            f.write(encoded(dict(slot=self.by_slot[key],plan_sha256=self.fingerprint,started_utc=now())))
            f.flush();os.fsync(f.fileno())
        return self.by_slot[key]

    def complete(self,key,row):
        claim,record,commit=self.paths(key)
        require(claim.exists() and not commit.exists(),'Missing claim or duplicate result')
        value=dict(row,slot=self.by_slot[key],plan_sha256=self.fingerprint,finished_utc=now())
        h=immutable(record,value)
        immutable(commit,dict(record_sha256=h,claim_sha256=sha(claim.read_bytes()),plan_sha256=self.fingerprint))
        return value

    def budget(self):
        rows={r['slot']['slot_id']:r for r in self.records()}
        claimed=[k for k in self.by_slot if self.paths(k)[0].exists()]
        reserved=sum(self.by_slot[k]['max_new_tokens'] for k in claimed)
        # All claims reserve their entire cap even if incomplete: never hide work.
        return dict(generation_attempts=len(claimed),reserved_tokens=reserved,
                    reserved_forwards=reserved+sum(self.by_slot[k]['mode']=='conditional' for k in claimed),
                    known_emitted_tokens=sum(r.get('generated_tokens',0) for r in rows.values()),
                    known_forward_attempts=sum(r.get('forward_attempts',0) for r in rows.values()),
                    incomplete_slots=self.unfinished(),completed_slots=len(rows),expected_slots=len(self.by_slot),
                    remaining_generation_slots=len(self.by_slot)-len(claimed),
                    remaining_reserved_token_allowance=sum(s['max_new_tokens'] for s in self.by_slot.values())-reserved,
                    remaining_forward_allowance=sum(s['max_new_tokens']+(s['mode']=='conditional') for s in self.by_slot.values())-reserved-sum(self.by_slot[k]['mode']=='conditional' for k in claimed))

    def disposition(self,key,reference):
        require(bool(reference.strip()),'Central disposition reference required')
        require(key in self.unfinished(),'Only unfinished slots can be disposed')
        # Preserve even a returned record published just before a disconnect.
        # Disposition is a separate immutable record; it never overwrites that evidence.
        claim,record,commit=self.paths(key)
        value=dict(status='abandoned',disposition=reference,response=None,generated_tokens=0,forward_attempts=0,
                   unknown_consumed_work=True,reason='Reserved maximum retained; no retry',
                   slot=self.by_slot[key],plan_sha256=self.fingerprint,finished_utc=now(),
                   unpublished_record_sha256=sha(record.read_bytes()) if record.exists() else None)
        disposition=record.with_name(key+'.disposition.json')
        h=immutable(disposition,value)
        immutable(commit,dict(record_file=disposition.name,record_sha256=h,claim_sha256=sha(claim.read_bytes()),
                              plan_sha256=self.fingerprint))
        return value

    def snapshot(self,status,extra=None):
        files={str(p.relative_to(self.path)):sha(p.read_bytes()) for p in sorted(self.path.rglob('*'))
               if p.is_file() and (p.parent.name=='slots' or p.name=='plan.json')}
        result=dict(schema=1,phase=self.plan['phase'],status=status,plan_sha256=self.fingerprint,
                    budget=self.budget(),files=files,extra=extra or {},created_utc=now())
        h=digest(result);immutable(self.path/'checkpoints'/(h+'.json'),result)
        atomic(self.path/'checkpoint-current.json',{'sha256':h})
        return h,result
