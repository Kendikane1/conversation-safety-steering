"""Explicit user-run cached-tokenizer check; no model or network work on import."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import atomic_json, digest, file_hash, serialize_prompt, utc, validate_data


def validate_cached_tokenizer(root, *, enabled=False):
    """Check all 64 fixtures with the pinned cached tokenizer; never load a model.

    Invoke in a freshly restarted accepted NCC kernel after central review.
    Uses existing CPU tensor support, no model/steering imports or CUDA calls.
    Reports are new files under work/, never written into a smoke-run directory.
    """
    if not enabled:
        raise RuntimeError("Cached-tokenizer validation disabled")
    root = Path(root).resolve()
    cfg = json.loads((root / "configs/w01_baseline.json").read_text())
    data = validate_data(root, cfg)
    # Set before importing the Hub/Transformers libraries in the fresh kernel.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    mid = cfg["model"]
    report = {"schema_version": 1, "check": "w01-cached-tokenizer-only", "started_utc": utc(),
              "status": "running", "tokenizer_id": mid["id"], "tokenizer_revision": mid["revision"],
              "local_files_only": True, "offline_environment": True,
              "model_loading": False, "generation": False,
              "configuration_sha256": digest(cfg),
              "contracts_sha256": file_hash(root / "src/lexsi_track2/contracts.py"),
              "validator_sha256": file_hash(Path(__file__)),
              "input_sha256": {split: file_hash(root / cfg["data"][split]) for split in data},
              "expected_cases": sum(len(rows) for rows in data.values()), "cases": [], "error": None}
    try:
        import transformers
        report["transformers_version"] = transformers.__version__
        selected = next(pin.split("==", 1)[1] for pin in cfg["dependencies"]["proposed_not_runtime_tested"]
                        if pin.startswith("transformers=="))
        if transformers.__version__ != selected:
            raise RuntimeError(f"Expected existing Transformers {selected}, got {transformers.__version__}; stop for review")
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            mid["id"], revision=mid["revision"], trust_remote_code=False, local_files_only=True)
        if not tokenizer.chat_template:
            raise RuntimeError("Cached tokenizer has no chat template")
        tokenizer.padding_side = "left"
        report["tokenizer_class"] = type(tokenizer).__name__
        report["chat_template_sha256"] = digest(tokenizer.chat_template)
        for split, rows in data.items():
            limit = (cfg["generation"]["max_input_tokens"] if split == "diagnostic"
                     else cfg["calibration"]["max_input_tokens"])
            for case in rows:
                row = {"case_id": case["case_id"], "split": split, "max_input_tokens": limit}
                try:
                    _, prompt = serialize_prompt(tokenizer, case["messages"], limit)
                    row.update(status="passed", input_tokens=prompt["input_tokens"],
                               messages_sha256=prompt["messages_sha256"], token_sha256=prompt["token_sha256"])
                except Exception as error:
                    row.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
                report["cases"].append(row)
        report["status"] = "passed" if all(row["status"] == "passed" for row in report["cases"]) else "failed"
    except Exception as error:
        report.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
    report["passed_cases"] = sum(row["status"] == "passed" for row in report["cases"])
    report["failed_cases"] = sum(row["status"] == "failed" for row in report["cases"])
    report["not_checked_cases"] = report["expected_cases"] - len(report["cases"])
    report["finished_utc"] = utc()
    stamp = report["finished_utc"].replace(":", "").replace("-", "").replace("+", "_")
    output = root / "work/tokenizer-validation" / f"w01-tokenizer-{stamp}-{uuid4().hex[:8]}.json"
    atomic_json(output, report)
    return output, report
