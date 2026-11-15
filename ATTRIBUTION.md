# Attribution and component terms

Muhammad Ariz Muhammad Akmal is the sole human project author. Substantial AI assistance supported implementation, operation, evidence preparation, analysis and drafting. Evaluation labels are assistant-only; separate assistant sessions do not establish independent model families or human validation. See [AUTHORSHIP.md](AUTHORSHIP.md).

Original code is MIT; original research contributions are CC BY 4.0 where rights are held. [Scoped licence](LICENSE.md) governs mixed documents and outputs. The file-level rights inventory records exceptions.

## Connected upstream toolkits

[SafeTune](https://github.com/Lexsi-Labs/SafeTune/tree/3901a9f48a88984a181c8c9493be2d3a20ab160f), revision `3901a9f48a88984a181c8c9493be2d3a20ab160f`, supplies CAST extraction and conditional activation steering. [AuditKIT](https://github.com/Lexsi-Labs/AuditKIT/tree/71316da345784ff220d5ed59337441a59ab31526), revision `71316da345784ff220d5ed59337441a59ab31526`, supplies the connected evaluation/reporting interface; project review labels and policy subgroups feed the audit rather than using gate activation as a safety label. Both are source-available under LSAL v1.2, not MIT or OSI open source. Full [SafeTune terms](LICENSES/upstream/SafeTune-LICENSE.md) and [AuditKIT terms](LICENSES/upstream/AuditKIT-LICENSE.md) are retained. Original adapters call their APIs; no blanket claim of toolkit ownership over numerical outputs is made.

## Model and derived evidence

[CohereLabs/Tiny Aya Global](https://huggingface.co/CohereLabs/tiny-aya-global), revision `af89d219b53ed9b13b8a4645f9c8028973510324`, is the gated source model. Its [Cohere CC BY-NC terms](https://cohere.com/cohere-labs-cc-by-nc-license) and [Acceptable Use Policy](https://docs.cohere.com/docs/cohere-labs-acceptable-use-policy) remain applicable. No checkpoint or tokenizer is rehosted. The steering artifact contains six activation vectors, not trained weights, an adapter or a merged checkpoint. Generated responses are identified in the evidence and are not automatically relicensed by this project. Original editorial and annotation contributions remain separately scoped.

## Source and evidence changes

[SOURCE_EDITS.json](SOURCE_EDITS.json) distinguishes accepted historical source hashes from edited public copies. Private runtime defaults use generic examples; an internal operator identifier is redacted. Edited output-bearing notebooks have separate per-cell provenance supplied with their exports. Redaction manifests identify removed fields and original-content hashes; measurements describe original unredacted runs, not retokenized public text. Original private execution notebooks remain authoritative. The new CPU notebook analyzes released rows and does not repeat model generation.
