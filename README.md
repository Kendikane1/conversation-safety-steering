# Conversation safety steering: negative replication and shared gate misses

**Changing the gate's readout did not establish a safety advantage.** On 128 authored families, U produced harmful assistance on 33/128 disallowed requests versus fitted B 28/128 and deployed B 33/128; both registered superiority criteria failed. In the separate W03H generated-history study, every responder had observed harm **3/22**, while quality filtering yielded **0/19**. The filtered zero is not harm-free performance.

By **Muhammad Ariz Muhammad Akmal**, with substantial AI assistance. All evaluation judgments are assistant-only; there was no human validation. [Authorship](AUTHORSHIP.md) · [Scoped licences](LICENSE.md).

[Read the canonical article](https://github.com/Kendikane1/conversation-safety-steering/blob/main/ARTICLE.md) · [Open the results report](https://arizakml-conversation-safety-steering.static.hf.space/report.html) · [Inspect reviewed conversations](https://arizakml-conversation-safety-steering.static.hf.space/index.html) · [Study coverage](STUDIES.md) · [Evidence and reproduction](EVIDENCE.md).

## What was tested

Inference-time safety steering, Lexsi Track 2b (item 8 in the combined Track 2 list, fourth Track 2b topic). SafeTune CAST extracts and applies activation directions; AuditKIT provides the connected evaluation/reporting interface. Tiny Aya Global, frozen vectors, steering strength and decoding are held fixed while comparing gate readouts. U averages hidden states at the final content token of each user message. B reads the final serialized prompt token, the assistant response-opening marker. No model training or adapter merge is performed.

The early diagnostic found fewer harmful answers under always-on steering (3/16 → 1/16) but lower useful help (16/16 → 14/16). W02 found no prespecified U benefit on previously inspected prompts. W03's small fixed-history comparison favored U on one fresh endpoint; the larger authored replication did not confirm that advantage. Generated-history development exposed context-length and semantic-eligibility failures. All stages, including failed and incomplete studies, remain separately described in [STUDIES.md](STUDIES.md).

W03H completed 132 responder answers from 144 reservations. Four over-cap contexts excluded 12 slots; another 12 completed answers failed primary quality requirements. Nine of those were harmful replies in one family, across three writers and three responders, with two distinct texts and every gate inactive. Primary available-pair differences were zero. All-reserved logical bounds are ±20.83 percentage points for disallowed harm and ±12.50 for allowed outcomes; neither constitutes a confidence interval or evidence of equivalence.

## Public evidence and CPU reproduction

Reviewed exports contain conversations, responses, outcomes, exclusions, measurement fields and hash-linked source provenance. Necessary text redactions are marked; original private execution archives and notebooks remain preserved. Token counts and hashes refer to original runs, not retokenized redacted text. The [viewer](viewer/index.html) separates observed answers, primary eligibility and missing reservations.

The [CPU reproduction notebook](reproduction/W03H_CPU_REPRODUCE.ipynb) starts with a reviewed input ZIP or explicit local folder, validates every input hash, and recomputes W03H counts, common-history pairs, family weights, missing-outcome bounds and changed-case IDs from rows. It uses Python's standard library; the optional Colab upload picker requires no Drive mount, install, model download or GPU. The [saved executed W03H copy](reproduction/W03H_CPU_REPRODUCE.executed.ipynb) preserves the completed seven-stage CPU run. A separate [historical/RF128 recovery-v2 notebook](reproduction/STUDIES_CPU_REPRODUCE_V2.ipynb) covers native study metrics and coverage. Its original v1 run stopped at an anchor-policy denominator check. The [saved combined execution](reproduction/STUDIES_V2_CPU_REPRODUCE.executed.ipynb) preserves that failure and the successful eight-stage v2 recovery; the [downloaded JSON result](reproduction/studies-public-reproduction-v2.json) records the completed checks. Follow numbered cells individually and retain outputs. See [EVIDENCE.md](EVIDENCE.md) for the distinction between source preparation and verified execution.

Historical experiment code and six edited saved-output notebook extracts document the methods. Six earlier final executed notebook snapshots were not located; the evidence guide and per-study status records disclose these gaps. They are not a public Run-all model reproduction bundle: original parent archives, authorised model access and a compatible environment are prerequisites. Public source changes are recorded in [SOURCE_EDITS.json](SOURCE_EDITS.json). The historical [synthesis notebook](synthesis.ipynb) has its original saved outputs and contains no W03H execution.

## Public destinations

- [Code and notebooks](https://github.com/Kendikane1/conversation-safety-steering)
- [Reviewed evidence dataset](https://huggingface.co/datasets/arizakml/conversation-steering-evidence) and [dataset collection](https://huggingface.co/collections/arizakml/conversation-safety-steering-evidence)
- [Six activation vectors](https://huggingface.co/arizakml/conversation-steering-vectors) and [model-artifact collection](https://huggingface.co/collections/arizakml/conversation-safety-steering-models)
- [Static Space](https://huggingface.co/spaces/arizakml/conversation-safety-steering)

The vector file is 49,600 bytes, not a checkpoint or trained adapter. Upstream weights/tokenizer remain gated and are not rehosted. Original code is MIT; original research contributions are CC BY 4.0 where rights are held. Upstream software and generated/model-derived content retain component notices and applicable restrictions.

This is a small, curated English evaluation of one model with correlated histories and assistant judgment bias. It supports an auditable negative finding and a shared failure to activate steering, not a deployment recommendation. See the article for uncertainty, failures, compute and next research steps.
