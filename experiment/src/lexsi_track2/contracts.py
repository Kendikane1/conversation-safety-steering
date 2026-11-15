"""Data, identity, and incremental run contracts; standard library only."""
from __future__ import annotations

import hashlib
import ast
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
from uuid import uuid4


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def atomic_jsonl(path, rows):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def notebook_source_hash(path):
    """Hash experimental code, excluding prose, outputs and execution switches."""
    controls = {"ALLOW_PLAN", "ALLOW_INSTALL", "ALLOW_SOURCES", "ALLOW_MODEL", "ALLOW_SMOKE",
                "ALLOW_CALIBRATION", "ALLOW_PILOT", "ALLOW_REVIEW", "REVIEWED_PLAN_SHA256",
                "SMOKE_REVIEW_REFERENCE", "PILOT_REVIEW_REFERENCE", "CALIBRATION_RUN_ID", "PILOT_RUN_ID"}
    cells = []
    for cell in json.loads(Path(path).read_text())["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        tree = ast.parse(source)
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id in controls):
                node.value = ast.Constant(value="<execution-control>")
        cells.append(ast.dump(tree, include_attributes=False))
    return digest(cells)


def source_identity(root, config=None):
    """Explicit W01 execution inputs; no Git/admin/platform state in this identity.

    Python modules below the implementation package are included recursively;
    notebook/configuration/pins/data/rubric paths are deliberately explicit.
    Full raw-file and revision provenance is captured separately.
    """
    root = Path(root).resolve()
    config_path = root / "configs/w01_baseline.json"
    if config is None:
        config = json.loads(config_path.read_text())
    package = root / "src/lexsi_track2"
    implementation = [p for p in package.rglob("*.py")
                      if not any(part.startswith(".") or part == "__pycache__"
                                 for part in p.relative_to(package).parts)]
    if not implementation:
        raise ValueError("Missing W01 implementation sources")
    paths = [*implementation, config_path, root / config["source_manifest"],
             *(root / config["data"][key] for key in ("diagnostic", "extraction", "development", "rubric"))]
    hashes = {}
    for p in sorted(set(paths)):
        resolved = p.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Execution inputs must be within the configured project root")
        hashes[str(p.relative_to(root))] = file_hash(p)
    notebook = root / "notebooks/01_baseline_diagnostic.ipynb"
    hashes[str(notebook.relative_to(root))] = notebook_source_hash(notebook)
    return {"identity_schema_version": 2, "source_hashes": hashes,
            "note": "Explicit implementation, notebook code, configuration, source pins, inputs and scoring rubric. Notebook controls are normalised. Revision and administrative/raw-file provenance are separate."}


def administrative_provenance(root):
    """Raw project/documentation/revision snapshot; never used for compatibility."""
    root = Path(root).resolve()
    paths = [p for top in ("src", "configs", "notebooks", "docs", "tests")
             for p in (root / top).rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    paths += [root / name for name in ("AGENTS.md", "README.md", ".gitignore") if (root / name).is_file()]
    hashes = {str(p.relative_to(root)): file_hash(p) for p in sorted(paths)}
    revision = None
    try:
        git_root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                            cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        if Path(git_root).resolve() == root:
            revision = subprocess.check_output(["git", "rev-parse", "--verify", "HEAD"],
                                               cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return {"revision": revision, "raw_file_sha256": hashes,
            "note": "Broad raw provenance, including documents, tests, notebook checkpoints and platform metadata where present. Excluded from experiment fingerprints. No clean-tree claim; no enclosing repository revision used."}


def validate_config(config):
    g, c, p = config["generation"], config["calibration"], config["pilot"]
    if (g["batch_size"] != 1 or not 1 <= g["max_input_tokens"] <= 1024
            or not 1 <= g["max_new_tokens"] <= 128 or g["do_sample"] is not False
            or g["num_beams"] != 1 or config["model"]["dtype"] != "bfloat16"
            or p["arms"] != ["base", "conditional", "always_on"]
            or p["endpoints"] != 32 or p["max_generations"] != 96
            or not 1 <= config["smoke"]["max_new_tokens"] <= 32):
        raise ValueError("Configuration exceeds reviewed pilot/smoke or changes matched arms")
    if (c["batch_size"] != 1 or c["pool"] != "last" or c["behavior_pool"] != "last_token"
            or c["behavior_normalize"] is not False or c["alpha"] != 1.0
            or c["extraction_per_class"] != 8 or c["development_per_class"] != 8
            or not 1 <= c["max_input_tokens"] <= 1024 or c["max_condition_layers"] != 3
            or c["threshold_range"] != [-1.0, 1.0] or c["threshold_step"] != 0.01
            or c["val_frac"] != 0.5):
        raise ValueError("Configuration changes the existing bounded source-supported baseline")


def validate_data(root, config):
    validate_config(config)
    splits = {s: load_jsonl(Path(root) / config["data"][s])
              for s in ("diagnostic", "extraction", "development")}
    all_ids = set()
    lineage_sets, topic_sets, message_sets, scenario_sets = [], [], [], []
    for split, rows in splits.items():
        if len(rows) != (32 if split == "diagnostic" else 16):
            raise ValueError(f"Unexpected {split} size")
        for r in rows:
            required = {"scenario_id", "case_id", "template_lineage", "messages", "split",
                        "topic", "expected_policy_action", "rationale", "provenance", "category",
                        "safe_utility_checklist", "forbidden_output_criteria"}
            if not required <= r.keys() or r["split"] != split:
                raise ValueError("Missing schema fields or wrong split")
            if r["case_id"] in all_ids:
                raise ValueError("Duplicate case id")
            all_ids.add(r["case_id"])
            if r["expected_policy_action"] not in {"allow", "refuse_harmful_part"}:
                raise ValueError("Ambiguous policy label must be reviewed")
            roles = [m["role"] for m in r["messages"]]
            if not roles or roles != ["user" if i % 2 == 0 else "assistant" for i in range(len(roles))] or roles[-1] != "user":
                raise ValueError("Invalid role order")
            if any(not isinstance(m["content"], str) or not m["content"].strip() for m in r["messages"]):
                raise ValueError("Empty message")
            if split != "diagnostic" and len(roles) != 1:
                raise ValueError("Fitting inputs must remain single-turn")
            if split == "diagnostic" and not {"category", "safe_utility_checklist", "forbidden_output_criteria"} <= r.keys():
                raise ValueError("Missing diagnostic rubric")
            if split == "diagnostic":
                if (r["category"] == "anchor") != (len(roles) == 1):
                    raise ValueError("Only standalone anchors may have no history")
                indices = r.get("prior_refusal_message_indices")
                if (not isinstance(indices, list) or any(type(i) is not int for i in indices)
                        or indices != sorted(set(indices))
                        or any(not 0 <= i < len(roles) - 1 or roles[i] != "assistant" for i in indices)
                        or type(r.get("has_prior_refusal")) is not bool
                        or r["has_prior_refusal"] != bool(indices)):
                    raise ValueError("Invalid authored prior-refusal annotation")
                history_type = ("no_history_anchor" if len(roles) == 1 else
                                "authored_refusal" if indices else "authored_clarification_only")
                if r.get("history_type") != history_type:
                    raise ValueError("History type disagrees with authored refusal annotation")
        lineage_sets.append({r["template_lineage"] for r in rows})
        topic_sets.append({r["topic"] for r in rows})
        message_sets.append({m["content"].casefold() for r in rows for m in r["messages"]})
        scenario_sets.append({r["scenario_id"] for r in rows})
        if len({digest(r["messages"]) for r in rows}) != len(rows):
            raise ValueError("Duplicate full input")
        if split != "diagnostic":
            families = {}
            for r in rows:
                families.setdefault(r["scenario_id"], []).append(r)
            if len(families) != 8 or any(len(rs) != 2 or {r["expected_policy_action"] for r in rs} != {"allow", "refuse_harmful_part"} for rs in families.values()):
                raise ValueError("Fitting split must have eight paired class-balanced families")
    for groups in (lineage_sets, topic_sets, message_sets, scenario_sets):
        for i, a in enumerate(groups):
            for b in groups[i + 1:]:
                if a & b:
                    raise ValueError("Split overlap: lineage, topic or text")
    diag = splits["diagnostic"]
    families = {}
    for row in diag:
        families.setdefault(row["scenario_id"], []).append(row)
    paired = [rs for rs in families.values() if len(rs) == 2]
    anchors = [rs[0] for rs in families.values() if len(rs) == 1]
    if len(paired) != 12 or len(anchors) != 8:
        raise ValueError("Need twelve pairs and eight anchors")
    counts = {}
    for a, b in paired:
        if (a["messages"][:-1] != b["messages"][:-1] or a["messages"][-1] == b["messages"][-1]
                or {a["expected_policy_action"], b["expected_policy_action"]} != {"allow", "refuse_harmful_part"}
                or a["category"] != b["category"] or a["template_lineage"] != b["template_lineage"]
                or any(a[key] != b[key] for key in ("has_prior_refusal", "prior_refusal_message_indices", "history_type"))):
            raise ValueError("Broken family pairing")
        counts[a["category"]] = counts.get(a["category"], 0) + 1
    expected = {k: 3 for k in ("ambiguous_clarification", "harmful_replacement", "repeated_followup", "topic_change")}
    if counts != expected or sum(r["expected_policy_action"] == "allow" for r in anchors) != 4:
        raise ValueError("Wrong category/anchor balance")
    coverage = diagnostic_coverage(diag)
    for group in coverage["by_category"].values():
        if not group["refusal_families"] or not group["clarification_only_families"]:
            raise ValueError("Every conversation category needs refusal and clarification-only history controls")
    return splits


def diagnostic_coverage(cases):
    """Summarise authored annotations; this is not a semantic refusal classifier."""
    by_category = {}
    for r in cases:
        if r["category"] == "anchor":
            continue
        group = by_category.setdefault(r["category"], {"refusal_families": [], "clarification_only_families": [],
                                                       "refusal_endpoints": 0, "clarification_only_endpoints": 0})
        key = "refusal" if r["has_prior_refusal"] else "clarification_only"
        if r["scenario_id"] not in group[key + "_families"]:
            group[key + "_families"].append(r["scenario_id"])
        group[key + "_endpoints"] += 1
    return {"endpoints": len(cases), "with_prior_refusal": sum(r["has_prior_refusal"] for r in cases),
            "clarification_only": sum(r["history_type"] == "authored_clarification_only" for r in cases),
            "anchors": sum(r["history_type"] == "no_history_anchor" for r in cases),
            "policy_counts": {action: sum(r["expected_policy_action"] == action for r in cases)
                              for action in ("allow", "refuse_harmful_part")},
            "by_category": by_category}


def serialize_prompt(tokenizer, messages, limit):
    """Use actual template twice; compare real tokens, never truncate or infer spans."""
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    direct = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=False)
    enc = tokenizer(text, add_special_tokens=False, return_tensors="pt", truncation=False)
    ids = enc["input_ids"][0].tolist()
    if hasattr(direct, "tolist"):
        direct = direct.tolist()
    if ids != direct:
        raise ValueError("Rendered/template token identity mismatch")
    if not 0 < len(ids) <= limit:
        raise ValueError(f"Input {len(ids)} tokens exceeds cap {limit}; no truncation allowed")
    mask = enc.get("attention_mask")
    if mask is None or mask[0].tolist() != [1] * len(ids):
        raise ValueError("Expected a single unpadded sequence with explicit attention mask")
    return enc, {"messages_sha256": digest(messages), "serialized_prompt": text,
                 "serialized_prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
                 "input_ids": ids, "token_sha256": digest(ids), "input_tokens": len(ids)}


class RunStore:
    """Atomic small-run journal. A started-but-unfinished call is never silently retried."""

    def __init__(self, root, stage, identity, run_id=None):
        root = Path(root)
        if stage not in {"smoke", "calibration", "pilot"}:
            raise ValueError("Invalid stage")
        if run_id is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"w01-{stamp}-{stage}-{uuid4().hex[:8]}"
        if not re.fullmatch(r"w01-\d{8}T\d{6}Z-" + stage + r"-[a-zA-Z0-9]+", run_id):
            raise ValueError("Invalid run ID")
        self.path = root / "runs" / run_id
        self.path.mkdir(parents=True, exist_ok=True)
        self.identity = identity
        self.fingerprint = digest(identity)
        mp = self.path / "manifest.json"
        existing = mp.exists()
        if existing:
            self.manifest = json.loads(mp.read_text())
            if self.manifest["fingerprint"] != self.fingerprint:
                raise ValueError("Changed source/config/data/runtime; use a new run ID")
            expected = self.manifest.get("artifacts", {}).get("records.jsonl")
            if expected and file_hash(self.path / "records.jsonl") != expected:
                raise ValueError("Journal/manifest hashes differ; preserve both and return for review")
            self.rows = load_jsonl(self.path / "records.jsonl")
        else:
            if any(self.path.iterdir()):
                raise ValueError("Nonempty run directory without manifest")
            self.rows = []
            self.manifest = {"schema_version": 1, "assignment": "W01", "stage": stage,
                             "run_id": run_id, "created_utc": utc(), "status": "prepared",
                             "fingerprint": self.fingerprint, "identity": identity, "artifacts": {}, "error": None}
            atomic_jsonl(self.path / "records.jsonl", [])
        for row in self.rows:
            if row.get("run_fingerprint") != self.fingerprint:
                raise ValueError("Stale record fingerprint")
            if row.get("response") is not None and row.get("response_sha256") != digest(row["response"]):
                raise ValueError("Response integrity mismatch")
            if "input_ids" in row and digest(row["input_ids"]) != row.get("token_sha256"):
                raise ValueError("Token integrity mismatch")
            if "serialized_prompt" in row and hashlib.sha256(row["serialized_prompt"].encode()).hexdigest() != row.get("serialized_prompt_sha256"):
                raise ValueError("Prompt integrity mismatch")
        keys = [(r.get("case_id"), r.get("arm")) for r in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate endpoint/arm records")
        if not existing:
            self.save()

    def save(self):
        atomic_jsonl(self.path / "records.jsonl", self.rows)
        self.manifest["updated_utc"] = utc()
        self.manifest["artifacts"] = {str(p.relative_to(self.path)): file_hash(p)
                                      for p in self.path.rglob("*")
                                      if p.is_file() and p.name != "manifest.json" and not p.name.endswith(".tmp")}
        atomic_json(self.path / "manifest.json", self.manifest)

    def completed(self, case_id, arm, fingerprint):
        hits = [r for r in self.rows if r.get("case_id") == case_id and r.get("arm") == arm]
        if any(r["endpoint_fingerprint"] != fingerprint for r in hits):
            raise ValueError("Changed endpoint identity")
        if hits and hits[-1]["status"] in {"ok", "truncated"}:
            return True
        if hits:
            raise ValueError("Unfinished/failed attempt preserved; inspect evidence and use a new run")
        return False

    def begin(self, row, cap):
        if len(self.rows) >= cap:
            raise ValueError("Workload cap reached (attempts count, including failures)")
        row = {**row, "status": "started", "started_utc": utc(), "run_fingerprint": self.fingerprint}
        self.rows.append(row)
        self.manifest["status"] = "running"
        self.save()
        return len(self.rows) - 1

    def finish(self, index, **values):
        self.rows[index].update(values, finished_utc=utc())
        self.save()

    def close(self, status, error=None):
        self.manifest.update(status=status, error=error)
        self.save()


def verify_bundle(path):
    """Run on a retrieved local copy; this readback establishes only this copy's hashes."""
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    for name, expected in manifest["artifacts"].items():
        p = (path / name).resolve()
        if not p.is_relative_to(path.resolve()) or file_hash(p) != expected:
            raise ValueError(f"Bundle hash mismatch: {name}")
    return {"verified_files": len(manifest["artifacts"]), "manifest_sha256": file_hash(path / "manifest.json")}
