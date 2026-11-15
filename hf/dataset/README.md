---
license: other
license_name: mixed-research-evidence-terms
license_link: LICENSE.md
language:
- en
task_categories:
- text-generation
tags:
- safety
- activation-steering
- negative-results
---
# Conversation safety steering · reviewed research evidence

By Muhammad Ariz Muhammad Akmal, with substantial AI assistance. The release provides reviewed case-level conversations, answers, measurements, judgments, exclusions and provenance across the W01/W02/W03 study sequence. **All behavioral judgments are assistant-only; there was no human validation.** Content may contain harmful requests and model responses, with necessary redactions visibly marked.

`reviewed-evidence.zip` contains `studies/<study>/slots.jsonl`, `contexts.jsonl`, analysis reports, notices, source hashes, redaction manifests and edited saved-output notebook exports where the original snapshot was located. Explicit notebook-status files identify missing snapshots; no output is reconstructed and called executed. `slots.jsonl` and `contexts.jsonl` at repository root provide concatenated previews with study IDs. `INVENTORY.json` binds repository files; the ZIP has its own member inventory.

Read [study coverage](https://github.com/Kendikane1/conversation-safety-steering/blob/main/STUDIES.md), [article](https://github.com/Kendikane1/conversation-safety-steering/blob/main/ARTICLE.md), [CPU notebooks](https://github.com/Kendikane1/conversation-safety-steering/tree/main/reproduction) and [interactive viewer](https://huggingface.co/spaces/arizakml/conversation-safety-steering). [Dataset collection](https://huggingface.co/collections/arizakml/conversation-safety-steering-evidence).

## Results and responsible interpretation

The 128-family authored replication found harmful assistance U 33/128, fitted B 28/128 and deployed B 33/128, failing both registered superiority criteria. In W03H each responder had observed harm 3/22 and quality-filtered primary harm 0/19. The filtered zero is not harm-free performance. All nine observed harmful rows in one family remain public descriptive evidence despite primary exclusion. Missing slots are unknown, not safe. Equal-family main paired differences were zero; logical sensitivity bounds are not confidence intervals or equivalence evidence.

The data are curated English scenarios for one checkpoint, with correlated histories, development reuse and assistant judgment bias. Separate studies, writer-policy conditions and CPU/L 4 cohorts must not be pooled as independent observations. The original failed context-eligibility studies and post hoc sensitivities remain explicitly separate. No deployment conclusion follows.

## Fields and provenance

Stable `study`, `row_id`, `slot_id`, `family_id`, `case_id`, `phase`, `arm`, `writer` and `branch` identify records. `messages` and `response` are reviewed text; null response means no observed answer in that row. `labels` describe original settled or uncertain judgments; native schemas differ by study. `eligibility` records primary/technical/semantic selection. `measurement` retains allowlisted source measurements. `source` links original archive/member/pointer hashes. `redactions` marks edited fields and original hashes. Original token lengths and hashes describe unredacted execution; they are not recomputed from sanitized public strings.

## Rights

Original authored scenarios, research prose and editorial/annotation contributions are CC BY 4.0 to the extent rights are held. Measurements are facts; no exclusive rights in facts or guaranteed copyright in assistant labels are asserted. Original code is MIT. Generated/model-derived text and third-party materials are excluded from an unqualified original-contribution grant. Tiny Aya Global provenance and applicable Cohere noncommercial/AUP conditions remain; SafeTune and AuditKIT retain LSAL v1.2. See scoped `LICENSE.md` and `ATTRIBUTION.md`. This dataset grants no additional upstream rights or commercial synthetic-data permission. No upstream model weights/tokenizer or private operational credentials, paths, reviewer-session identifiers or blinding keys are included.
