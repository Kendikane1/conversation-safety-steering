---
license: other
license_name: scoped-research-artifact-terms
license_link: LICENSE.md
language:
- en
tags:
- activation-steering
- safety
- research
base_model: CohereLabs/tiny-aya-global
---
# Conversation safety steering · extracted activation vectors

By Muhammad Ariz Muhammad Akmal, with substantial AI assistance. This repository contains **six extracted activation vectors**: five behavior directions and one condition direction, stored in `steering.safetensors` (49,600 bytes). It contains no trained adapter, merged checkpoint, model weights or tokenizer.

The vectors were extracted using SafeTune CAST from gated Tiny Aya Global revision `af89d219b53ed9b13b8a4645f9c8028973510324`. `steering.json` records tensor/configuration provenance; `w02-readouts.json` records frozen gate settings. Behavior strength is 0.0625 at blocks 16–20. B reads the final serialized token at condition block 27; U averages hidden states at user-message content endpoints. The evaluated thresholds are U 0.12, fitted B 0.21 and deployed B 0.3700000000000012. Use the source configurations for exact settings.

**Result:** the 128-family authored replication failed both registered superiority criteria (U harm 33/128 versus fitted B 28/128 and deployed B 33/128). W03H found no measured main paired advantage and shared observed harmful gate misses. No deployment recommendation or safety guarantee is made. These vectors are a research artifact, not an endorsed safety product.

[Research article and source](https://github.com/Kendikane1/conversation-safety-steering/blob/main/ARTICLE.md) · [Dataset](https://huggingface.co/datasets/arizakml/conversation-steering-evidence) · [Static viewer](https://huggingface.co/spaces/arizakml/conversation-safety-steering) · [Model-artifact collection](https://huggingface.co/collections/arizakml/conversation-safety-steering-models).

## Terms and attribution

The vectors are excluded from an unqualified MIT or CC BY grant. Their upstream source is [Tiny Aya Global](https://huggingface.co/CohereLabs/tiny-aya-global), under [Cohere CC BY-NC terms](https://cohere.com/cohere-labs-cc-by-nc-license) and its [Acceptable Use Policy](https://docs.cohere.com/docs/cohere-labs-acceptable-use-policy). This notice preserves applicable upstream conditions without asserting that every extracted activation is necessarily a copyrighted derivative; it grants no additional upstream rights. SafeTune and AuditKIT retain their pinned LSAL v1.2 terms. Original card prose is CC BY 4.0 where rights are held. See `LICENSE.md` and `ATTRIBUTION.md` supplied with this repository.

This file does not run inference. Repeating extraction/inference requires authorized upstream model access and a compatible environment. No model download or installation is required to inspect the vectors or public CPU analysis. Behavioral labels are assistant-only, with no human validation.
