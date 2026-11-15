"""Explicit user-run NCC stages. No target libraries are imported at module import."""
from __future__ import annotations

import json
from pathlib import Path
import platform
import sys
import time

from .contracts import (RunStore, atomic_json, digest, file_hash, load_jsonl, utc,
                        administrative_provenance, serialize_prompt, source_identity,
                        validate_config, validate_data)
from .observe import generate_arm, observe_cast
from .setup import installed_versions, load_auditkit, load_safetune, verify_sources


def identity(root, cfg, stage, runtime=None):
    validate_config(cfg)
    root = Path(root)
    sources = json.loads((root / cfg["source_manifest"]).read_text())
    result = {"configuration": cfg, "configuration_sha256": digest(cfg),
              "source": source_identity(root, cfg), "stage": stage,
              "python": sys.version, "versions": installed_versions(),
              "model": cfg["model"], "tokenizer_revision": cfg["model"]["revision"],
              "tools": sources["repositories"], "seed": cfg["seed"],
              "input_hashes": {key: file_hash(root / cfg["data"][key]) for key in ("diagnostic", "extraction", "development", "rubric")}}
    if runtime is not None:
        result["runtime_identity"] = {key: runtime["info"][key] for key in (
            "gpu", "gpu_total_bytes", "cuda_version", "decoder_layers", "behavior_layers",
            "condition_candidates", "tokenizer_chat_template_sha256")}
    return result


def new_store(root, cfg, stage, run_id=None, runtime=None):
    store = RunStore(root, stage, identity(root, cfg, stage, runtime), run_id)
    record_notebook_snapshot(store, root)
    return store


def record_notebook_snapshot(store, root):
    provenance = administrative_provenance(root)
    now = utc()
    store.manifest.setdefault("provenance_snapshots", []).append({"utc": now, **provenance})
    store.manifest.setdefault("notebook_file_snapshots", []).append({"utc": now, "sha256": {
        name: value for name, value in provenance["raw_file_sha256"].items()
        if Path(name).parent == Path("notebooks") and name.endswith(".ipynb")}})
    # Do not rewrite existing artifact hashes before calibration's readback check.
    atomic_json(store.path / "manifest.json", store.manifest)


def load_target(root, cfg, *, enabled=False):
    if not enabled:
        raise RuntimeError("Target downloads/model execution disabled")
    validate_config(cfg)
    verify_sources(root)
    if sys.version_info < (3, 12):
        raise RuntimeError("Pinned SafeTune declares Python >=3.12; use the accepted NCC kernel")
    import importlib.metadata as metadata
    for requirement in cfg["dependencies"]["proposed_not_runtime_tested"]:
        name, selected = requirement.split("==")
        if metadata.version(name) != selected:
            raise RuntimeError(f"Actual {name} does not match the reviewed pin {selected}")
    for name, reported in cfg["dependencies"]["preserve_reported"].items():
        if metadata.version(name).split("+")[0] != reported:
            raise RuntimeError(f"Actual {name} differs from reported {reported}; record for review")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("Reviewed CUDA BF16 condition unavailable; no dtype/offload fallback")
    torch.manual_seed(cfg["seed"])
    torch.cuda.manual_seed_all(cfg["seed"])
    mid = cfg["model"]
    tokenizer = AutoTokenizer.from_pretrained(mid["id"], revision=mid["revision"], trust_remote_code=False)
    if not tokenizer.chat_template:
        raise RuntimeError("Candidate has no chat template")
    tokenizer.padding_side = "left"
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        mid["id"], revision=mid["revision"], dtype=torch.bfloat16,
        device_map={"": mid["device"]}, low_cpu_mem_usage=True,
        trust_remote_code=False, attn_implementation="sdpa")
    model.eval()
    model.requires_grad_(False)
    torch.cuda.synchronize()
    if model.config.model_type != "cohere2" or any(p.device.type != "cuda" for p in model.parameters()):
        raise RuntimeError("Unexpected architecture or offload; stop for review")
    if any(p.dtype != torch.bfloat16 for p in model.parameters()):
        raise RuntimeError("Unexpected parameter dtype; stop for review")
    cast_module, extraction, helpers = load_safetune(root)
    layers = helpers._get_decoder_layers(model)
    if not layers or len(layers) != model.config.num_hidden_layers:
        raise RuntimeError("Decoder mapping differs from model configuration")
    names = {id(m): name for name, m in model.named_modules()}
    n = len(layers)
    behavior = list(range(min(n - 1, round(14 * n / 32)), min(n - 1, round(18 * n / 32)) + 1))
    condition = sorted({max(1, min(n - 1, i * n // 4)) for i in (1, 2, 3)})
    if n < 4 or len(condition) > cfg["calibration"]["max_condition_layers"]:
        raise RuntimeError("Unexpected model depth")
    properties = torch.cuda.get_device_properties(0)
    free, total = torch.cuda.mem_get_info()
    info = {"platform": platform.platform(), "cpu_affinity": None,
            "gpu": properties.name, "gpu_total_bytes": total, "gpu_free_bytes_after_load": free,
            "cuda_version": torch.version.cuda, "load_seconds": time.perf_counter() - start,
            "peak_allocated_bytes_load": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes_load": torch.cuda.max_memory_reserved(),
            "model_configuration": model.config.to_dict(),
            "model_generation_configuration": model.generation_config.to_dict(),
            "tokenizer_chat_template_sha256": digest(tokenizer.chat_template),
            "decoder_layers": [{"index": i, "module": names[id(m)], "type": type(m).__name__}
                               for i, m in enumerate(layers)],
            "behavior_layers": behavior, "condition_candidates": condition}
    try:
        import os
        info["cpu_affinity"] = sorted(os.sched_getaffinity(0))
        info["reported_slurm_environment"] = {key: os.environ.get(key) for key in (
            "SLURM_JOB_ID", "SLURM_CPUS_PER_TASK", "SLURM_MEM_PER_NODE", "SLURM_JOB_GPUS")}
    except AttributeError:
        pass
    return {"model": model, "tokenizer": tokenizer, "cast_module": cast_module,
            "extraction_module": extraction, "helpers": helpers, "info": info}


def preflight(root, cfg, runtime, output_path=None):
    """All input caps checked before calibration/pilot; compare upstream fitting tokens."""
    data = validate_data(root, cfg)
    tok = runtime["tokenizer"]
    report = []
    for split, rows in data.items():
        limit = cfg["generation"]["max_input_tokens"] if split == "diagnostic" else cfg["calibration"]["max_input_tokens"]
        for r in rows:
            try:
                enc, prompt = serialize_prompt(tok, r["messages"], limit)
                if split != "diagnostic":
                    other = runtime["helpers"]._encode_prompts(tok, [r["messages"][0]["content"]],
                                                              True, return_tensors="pt", padding=True, truncation=True)
                    if other["input_ids"][0].tolist() != prompt["input_ids"]:
                        raise ValueError("Upstream fitting tokens differ from preflight tokens")
            except Exception as e:
                report.append({"case_id": r["case_id"], "split": split, "status": "error", "error": str(e)})
                if output_path:
                    atomic_json(output_path, report)
                raise ValueError(f"{split}/{r['case_id']}: {e}") from e
            report.append({"case_id": r["case_id"], "split": split, "input_tokens": prompt["input_tokens"],
                           "token_sha256": prompt["token_sha256"], "status": "ok"})
            if output_path:
                atomic_json(output_path, report)
    return data, report


def _eos_ids(value):
    values = [value] if type(value) is int else value
    if not isinstance(values, list) or not values or any(type(i) is not int or i < 0 for i in values):
        raise ValueError("Model generation EOS must be an integer or nonempty list of nonnegative integers")
    return values


def stopping_contract(model, tok):
    """Use model generation semantics, never the tokenizer's chat-turn default."""
    eos = getattr(getattr(model, "generation_config", None), "eos_token_id", None)
    source = "model.generation_config.eos_token_id"
    if eos is None:
        eos = getattr(getattr(model, "config", None), "eos_token_id", None)
        source = "model.config.eos_token_id"
    _eos_ids(eos)  # Missing/invalid model EOS is a reviewable error, not a tokenizer fallback.
    return {"eos_token_id": list(eos) if isinstance(eos, list) else eos, "source": source,
            "model_config_eos_token_id": getattr(getattr(model, "config", None), "eos_token_id", None),
            "tokenizer_eos_token_id": tok.eos_token_id}


def is_length_truncated(generated_ids, max_new_tokens, eos_token_id):
    """Only a final configured EOS completes a sequence that reaches the cap."""
    eos = _eos_ids(eos_token_id)
    return len(generated_ids) >= max_new_tokens and (not generated_ids or generated_ids[-1] not in eos)


def generation_settings(cfg, tok, model, max_new_tokens=None):
    g = cfg["generation"]
    return {"max_new_tokens": max_new_tokens or g["max_new_tokens"], "do_sample": False,
            "num_beams": 1, "use_cache": g["use_cache"],
            "cache_implementation": g["cache_implementation"],
            "pad_token_id": tok.pad_token_id, "eos_token_id": stopping_contract(model, tok)["eos_token_id"]}


def generate_record(runtime, cfg, case, arm, cast=None, smoke=False):
    import torch
    model, tok = runtime["model"], runtime["tokenizer"]
    inputs, prompt = serialize_prompt(tok, case["messages"], cfg["generation"]["max_input_tokens"])
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    settings = generation_settings(cfg, tok, model, cfg["smoke"]["max_new_tokens"] if smoke else None)
    torch.manual_seed(cfg["seed"])
    torch.cuda.manual_seed_all(cfg["seed"])
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    free_before, _ = torch.cuda.mem_get_info()
    start = time.perf_counter()
    with torch.inference_mode():
        if smoke:
            output = model.generate(**inputs, **settings)
            trace = {"gate_calls": [], "intervention_calls": 0, "actual_intervention": False}
        else:
            output, trace = generate_arm(model, cast, arm, inputs, settings)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    if not torch.equal(output[0, :prompt["input_tokens"]], inputs["input_ids"][0]):
        raise RuntimeError("Generation output lost the supplied prompt")
    new = output[0, prompt["input_tokens"]:].tolist()
    response = tok.decode(new, skip_special_tokens=True)
    eos = _eos_ids(settings["eos_token_id"])
    truncated = is_length_truncated(new, settings["max_new_tokens"], settings["eos_token_id"])
    finish_reason = "length" if truncated else "eos_token" if new and new[-1] in eos else "other"
    gate = trace["gate_calls"][0] if trace["gate_calls"] else None
    if gate is not None:
        gate = {**gate, "condition_layer": cast.condition_layer, "pool": cast.pool,
                "selected_token_count": 1, "available_unpadded_tokens": prompt["input_tokens"],
                "threshold": cast.threshold, "comparator": cast.comparator,
                "comparator_operation": ">" if cast.comparator == "smaller" else "<",
                "score_source": "exact return of upstream _gate_fires consumed by generate"}
    return {**prompt, "response": response, "response_sha256": digest(response),
            "generated_ids": new, "generated_tokens": len(new), "generation_settings": settings,
            "stopping_contract": stopping_contract(model, tok), "finish_reason": finish_reason,
            "status": "truncated" if truncated else "ok", "gate": gate,
            "behavior_layers": runtime["info"]["behavior_layers"] if cast else [],
            "behavior_strength": cast.alpha if cast else None, "intervention_trace": trace,
            "seconds": elapsed, "timing_scope": "CUDA-synchronised generation including gate prefill if conditional; excludes tokenization/load",
            "gpu_free_bytes_before": free_before, "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved()}


def smoke(root, cfg, *, enabled=False, run_id=None):
    if not enabled:
        raise RuntimeError("Smoke disabled")
    store = new_store(root, cfg, "smoke", run_id)
    if store.rows:
        raise RuntimeError("Smoke attempts are preserved; use a new smoke run instead of repeating in place")
    try:
        runtime = load_target(root, cfg, enabled=True)
        store.manifest["hardware"] = runtime["info"]
        _, token_report = preflight(root, cfg, runtime, store.path / "token_preflight.json")
        atomic_json(store.path / "token_preflight.json", token_report)
        # Harmless synthetic API smoke only; no inference, external judge or key.
        from .review import evaluate_manual, record_key
        ak = load_auditkit(root)
        r = {"case_id": "api-smoke", "arm": "base", "endpoint_fingerprint": "synthetic",
             "run_fingerprint": "synthetic", "response": "A helpful answer", "response_sha256": digest("A helpful answer"), "status": "ok"}
        label = {"review_id": record_key(r), "case_id": r["case_id"], "response_sha256": r["response_sha256"],
                 "status": "reviewed", "reviewer": "synthetic-check", "reason": "Known harmless fixture",
                 "harmful_content": False, "useful_safe_completion": True, "unnecessary_refusal": False,
                 "safe_redirection_or_partial_help": False, "invalid": False}
        audit = evaluate_manual(ak, [r], [label], [{"case_id": "api-smoke", "expected_policy_action": "allow"}], "synthetic")
        if (audit["metrics"].get("harmful_content") != {"count": 1, "mean": 0.0}
                or audit["metrics"].get("useful_safe_completion") != {"count": 1, "mean": 1.0}):
            raise RuntimeError("AuditKIT smoke returned unexpected denominator or value")
        atomic_json(store.path / "auditkit_smoke.json", audit)
        case = {"case_id": "smoke-benign", "messages": [{"role": "user", "content": cfg["smoke"]["prompt"]}]}
        index = store.begin({"case_id": case["case_id"], "scenario_id": "smoke", "arm": "base",
                             "endpoint_fingerprint": digest(case)}, cap=1)
        result = generate_record(runtime, cfg, case, "base", smoke=True)
        store.finish(index, **result)
        store.close("user_executed_smoke_pending_review")
        return runtime, store
    except BaseException as e:
        store.close("failed", {"type": type(e).__name__, "message": str(e)})
        raise


def calibrate(root, cfg, runtime, *, enabled=False, run_id=None):
    if not enabled:
        raise RuntimeError("Calibration disabled; reviewed smoke required")
    import torch
    store = new_store(root, cfg, "calibration", run_id, runtime)
    module, extraction = runtime["cast_module"], runtime["extraction_module"]
    try:
        store.manifest["hardware"] = runtime["info"]
        if (store.path / "assets.json").exists():
            if store.manifest["status"] != "user_executed_calibration_pending_review":
                raise RuntimeError("Calibration was not completed; preserve it and use a new run")
            if file_hash(store.path / "assets.json") != store.manifest["artifacts"].get("assets.json"):
                raise ValueError("Calibration metadata changed")
            assets = json.loads((store.path / "assets.json").read_text())
            if assets["calibration_fingerprint"] != store.fingerprint or assets["condition"]["pool"] != "last":
                raise ValueError("Calibration identity/pool changed")
            for name, expected in assets["hashes"].items():
                if file_hash(store.path / name) != expected:
                    raise ValueError("Calibration asset hash mismatch")
            tensors = torch.load(store.path / "vectors.pt", map_location="cpu", weights_only=True)
            condition = module.CASTCondition(condition_vector=tensors["condition"], **assets["condition"])
            cast = module.CASTModel(runtime["model"], tensors["behavior"], condition=condition, alpha=cfg["calibration"]["alpha"], per_prompt_gate=True)
            return cast, store
        if store.rows:
            raise RuntimeError("Interrupted calibration preserved; new run required (no duplicate extraction)")
        data, report = preflight(root, cfg, runtime, store.path / "token_preflight.json")
        atomic_json(store.path / "token_preflight.json", report)
        c = cfg["calibration"]
        idx = store.begin({"case_id": "fit", "arm": "calibration", "endpoint_fingerprint": digest(c)}, cap=1)
        def texts(split, action):
            return [r["messages"][0]["content"] for r in data[split] if r["expected_policy_action"] == action]
        # Same positive=harmful, negative=benign convention as CASTTrainer.
        # Lower-level extractor exposes batch_size; last-token math is unchanged.
        ve_cfg = extraction.VectorExtractionConfig(target_layers=runtime["info"]["behavior_layers"],
                    batch_size=1, pool_method=c["behavior_pool"], normalize=c["behavior_normalize"])
        ext = extraction.SteeringVectorExtractor(runtime["model"], runtime["tokenizer"], ve_cfg)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        with torch.inference_mode():
            vectors = ext.extract(safe_prompts=texts("extraction", "refuse_harmful_part"),
                                  unsafe_prompts=texts("extraction", "allow"))
            condition = module.fit_cast_condition(runtime["model"], texts("development", "refuse_harmful_part"),
                texts("development", "allow"), runtime["tokenizer"],
                candidate_layers=runtime["info"]["condition_candidates"],
                threshold_range=tuple(c["threshold_range"]), threshold_step=c["threshold_step"],
                val_frac=c["val_frac"], chat_template=True)
        if condition.pool != "last" or set(vectors) != set(runtime["info"]["behavior_layers"]):
            raise ValueError("Source defaults/layer coverage differ from reviewed baseline")
        fit_diagnostics = {k: getattr(condition, k) for k in ("condition_layer", "threshold", "comparator", "f1", "pool")}
        fit_diagnostics["behavior_vector_norms"] = {str(k): float(v.float().norm()) for k, v in vectors.items()}
        atomic_json(store.path / "fit_diagnostics.json", fit_diagnostics)
        if condition.f1 <= 0:
            torch.save({"behavior": {int(k): v.cpu() for k, v in vectors.items()},
                        "condition": condition.condition_vector.cpu()}, store.path / "failed_fit_vectors.pt")
            raise RuntimeError("Upstream calibration returned fallback F1=0; preserve evidence, review before pilot")
        cast = module.CASTModel(runtime["model"], vectors, condition=condition, alpha=c["alpha"], per_prompt_gate=True)
        # Real gate observer equivalence, using a development input only. Two forwards.
        enc, _ = serialize_prompt(runtime["tokenizer"], data["development"][0]["messages"], c["max_input_tokens"])
        enc = {k: v.to(runtime["model"].device) for k, v in enc.items()}
        with torch.inference_mode():
            plain = cast._gate_fires(**enc)
            with observe_cast(cast) as trace:
                observed = cast._gate_fires(**enc)
        torch.cuda.synchronize()
        atomic_json(store.path / "observer_equivalence.json", {"plain": plain, "observed": observed, "trace": trace})
        if plain != observed or len(trace["gate_calls"]) != 1 or trace["intervention_calls"]:
            raise RuntimeError("Real gate observer equivalence failed")
        tensors = {"behavior": {int(k): v.cpu() for k, v in vectors.items()}, "condition": condition.condition_vector.cpu()}
        torch.save(tensors, store.path / "vectors.pt")
        cond_data = {k: getattr(condition, k) for k in ("condition_layer", "threshold", "comparator", "f1", "pool")}
        assets = {"condition": cond_data, "hashes": {"vectors.pt": file_hash(store.path / "vectors.pt")},
                  "calibration_fingerprint": store.fingerprint, "observer_equivalence": {"plain": plain, "observed": observed},
                  "behavior_vectors": "un-normalized harmful-minus-benign last-token prompt means; not a verified refusal direction",
                  "fit_split_rule": "per class 8: train [1,3,5,7], validation [0,2,4,6] in class order"}
        atomic_json(store.path / "assets.json", assets)
        store.finish(idx, status="ok", seconds=time.perf_counter() - start, assets=assets,
                     peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                     peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                     timing_scope="extraction, condition fitting and two observer equivalence prefills")
        store.close("user_executed_calibration_pending_review")
        return cast, store
    except BaseException as e:
        store.close("failed", {"type": type(e).__name__, "message": str(e)})
        raise


def pilot(root, cfg, runtime, cast, calibration_store, *, enabled=False, run_id=None):
    if not enabled:
        raise RuntimeError("Pilot disabled; central smoke/config/labels review required")
    if calibration_store.fingerprint != digest(identity(root, cfg, "calibration", runtime)):
        raise ValueError("Changed calibration provenance")
    assets = json.loads((calibration_store.path / "assets.json").read_text())
    if (cast.model is not runtime["model"] or cast.alpha != cfg["calibration"]["alpha"]
            or not cast.per_prompt_gate
            or sorted(cast.steering_vectors) != runtime["info"]["behavior_layers"]
            or any(getattr(cast, key) != assets["condition"][key]
                   for key in ("condition_layer", "threshold", "comparator", "pool"))):
        raise ValueError("In-memory baseline differs from saved calibration/configuration")
    for name, expected in assets["hashes"].items():
        if file_hash(calibration_store.path / name) != expected:
            raise ValueError("Changed calibration assets")
    ident = identity(root, cfg, "pilot", runtime)
    ident["calibration"] = {"fingerprint": calibration_store.fingerprint, "assets_sha256": file_hash(calibration_store.path / "assets.json")}
    store = RunStore(root, "pilot", ident, run_id)
    record_notebook_snapshot(store, root)
    try:
        data, report = preflight(root, cfg, runtime, store.path / "token_preflight.json")
        store.manifest["hardware"] = runtime["info"]
        atomic_json(store.path / "token_preflight.json", report)
        for case in data["diagnostic"]:
            for arm in cfg["pilot"]["arms"]:
                _, prompt = serialize_prompt(runtime["tokenizer"], case["messages"], cfg["generation"]["max_input_tokens"])
                fp = digest({"case": case, "arm": arm, "tokens": prompt["token_sha256"], "run": store.fingerprint})
                if store.completed(case["case_id"], arm, fp):
                    continue
                index = store.begin({"scenario_id": case["scenario_id"], "case_id": case["case_id"], "arm": arm,
                                     "history_type": case["history_type"], "has_prior_refusal": case["has_prior_refusal"],
                                     "prior_refusal_message_indices": case["prior_refusal_message_indices"],
                                     "endpoint_fingerprint": fp, **prompt}, cfg["pilot"]["max_generations"])
                try:
                    result = generate_record(runtime, cfg, case, arm, cast)
                    store.finish(index, **result)
                except BaseException as e:
                    store.finish(index, status="error", error={"type": type(e).__name__, "message": str(e)})
                    raise
        from .review import export_review
        export_review(store, data["diagnostic"])
        store.close("user_executed_pending_manual_review")
        return store
    except BaseException as e:
        store.close("failed", {"type": type(e).__name__, "message": str(e)})
        raise
