"""W02 live adapter around the accepted W01D model and generation path."""
from unittest.mock import patch
import conversation_compute as compute
import conversation_model as original
from conversation_state import require, sha, digest
from readout_science import positions, observe


class Session:
    def __init__(self, adopted, baseline):
        self.adopted = adopted
        self.baseline = baseline
        self.runtime, self.saved, self.assets, self.cfg, self.before = compute.load(adopted, baseline)
        self.params = original.parameter_metadata(self.runtime['model'])

    def run(self, case, slot, policy=None):
        from lexsi_track2.contracts import serialize_prompt
        runtime = self.runtime
        inputs, prompt = serialize_prompt(runtime['tokenizer'], case['messages'], 512)
        proof = positions(case['messages'],prompt,runtime['tokenizer'])
        result = dict(case_id=case['case_id'], messages=case['messages'], **prompt)
        def capture(cast, stock, tensors):
            require('scores' not in result, 'Repeated gate call')
            result.update(observe(cast,runtime['cast_module'],stock,tensors,proof))
        if policy is None:
            cast = original.make_cast(runtime,self.saved,self.assets,.0625)
            require(not original.hooks(runtime['model']), 'Foreign model hooks')
            tensors = {k:inputs[k].to(runtime['model'].device) for k in ('input_ids','attention_mask')}
            capture(cast,cast._gate_fires,tensors)
            require(not original.hooks(runtime['model']), 'Leaked condition hook')
            return dict(result,status='ok',generated_tokens=0,forward_attempts=1)
        make = original.make_cast
        def factory(*args):
            cast = make(*args)
            stock = cast._gate_fires
            def replacement(input_ids, **kwargs):
                capture(cast, stock, dict(input_ids=input_ids,**kwargs))
                require(all(abs(result['scores'][a]-s)<=1e-6 for a,s in policy['expected_scores'].items()), 'Frozen comparison score drift')
                score = result['scores'][policy['arm']]
                decision = score > policy['cutoff']
                require(abs(score-policy['score'])<=1e-6 and decision==policy['decision'], 'Verification score or routing drift before generation')
                return [decision], [score]
            cast._gate_fires = replacement
            return cast
        with patch.object(original,'make_cast',factory):
            fresh = original.generate(runtime,self.cfg,self.baseline,case,slot,self.saved,self.assets)
        if fresh['status']!='ok':
            return dict(fresh,**{k:v for k,v in result.items() if k in ('scores','proof','stock_score','stock_decision')})
        fresh['stock_readout']=fresh.pop('gate_readout',None)
        fresh['gate_readout']=dict(arm=policy['arm'],indices=proof['indices'][policy['arm']],layer=27,
                                   cutoff=policy['cutoff'],comparator='smaller',score=result['scores'][policy['arm']],
                                   decision=policy['decision'],proof_sha256=proof.get('proof_sha256'))
        fresh['readout_configuration_sha256']=digest(dict(generation=fresh.get('derived_configuration_sha256'),
                                                         arm=policy['arm'],cutoff=policy['cutoff'],layer=27))
        return dict(fresh,**{k:result[k] for k in ('scores','proof','stock_score','stock_decision')})

    def close(self):
        vectors = [('condition', self.saved['condition']),*((str(k),v) for k,v in self.saved['behavior'].items())]
        after = {k:sha(v.detach().float().cpu().contiguous().numpy().tobytes()) for k,v in vectors}
        require(after==self.before and original.parameter_metadata(self.runtime['model'])==self.params and
                sha((self.adopted['calibration']/'vectors.pt').read_bytes())==self.baseline['vectors_sha256'] and
                not original.hooks(self.runtime['model']), 'Model/vector/hook postcondition failed')
