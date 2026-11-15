"""Explicit, user-invoked setup. No action happens at import time."""
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import urllib.request

from .contracts import atomic_json, file_hash


def fetch_sources(root, *, enabled=False):
    if not enabled:
        raise RuntimeError("Source downloads disabled")
    root = Path(root)
    spec = json.loads((root / "configs/w01_sources.json").read_text())
    vendor = root / "work/vendor"
    for entry in spec["files"]:
        dest = vendor / entry["repository"] / entry["path"]
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = urllib.request.urlopen(entry["url"], timeout=30).read()
            import hashlib
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"Source hash mismatch: {dest}")
            dest.write_bytes(data)
        if file_hash(dest) != entry["sha256"]:
            raise ValueError(f"Existing source changed: {dest}; preserve it and review")
    return verify_sources(root)


def verify_sources(root, vendor=None):
    root = Path(root)
    vendor = Path(vendor) if vendor else root / "work/vendor"
    spec = json.loads((root / "configs/w01_sources.json").read_text())
    for entry in spec["files"]:
        p = vendor / entry["repository"] / entry["path"]
        if not p.is_file() or file_hash(p) != entry["sha256"]:
            raise ValueError(f"Missing/changed pinned source: {p}")
    return vendor


def load_auditkit(root, vendor=None):
    vendor = verify_sources(root, vendor)
    source = (vendor / "auditkit/src").resolve()
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    ak = importlib.import_module("auditkit")
    if not Path(ak.__file__).resolve().is_relative_to(source):
        raise RuntimeError("Another AuditKIT is loaded; restart kernel with the pinned sources")
    return ak


def load_safetune(root, vendor=None):
    """Execute licensed upstream modules unchanged, omitting eager package initialisers.

    A dedicated fresh notebook kernel is required. We create package namespaces
    for the absolute imports used in the pinned files; no upstream functions are
    copied, edited, or replaced. This is an import adapter, not a full install.
    """
    vendor = verify_sources(root, vendor)
    base = (vendor / "safetune/src/safetune").resolve()
    if "safetune" in sys.modules:
        mod = sys.modules["safetune"]
        if getattr(mod, "_w01_source", None) != str(base):
            raise RuntimeError("SafeTune already imported through another route; restart kernel")
    else:
        packages = ["safetune", "safetune.interventions", "safetune.interventions.steer",
                    "safetune.core", "safetune.core.runtime", "safetune.core.runtime.inference"]
        for name in packages:
            mod = types.ModuleType(name)
            mod.__path__ = [str(base.joinpath(*name.split(".")[1:]))]
            mod.__package__ = name
            mod._w01_source = str(base)
            sys.modules[name] = mod
    cast = importlib.import_module("safetune.interventions.steer.cast")
    vectors = importlib.import_module("safetune.core.runtime.inference.vector_extraction")
    helpers = importlib.import_module("safetune._refusal_helpers")
    return cast, vectors, helpers


def installed_versions():
    return {d.metadata["Name"]: d.version for d in metadata.distributions() if d.metadata["Name"]}


def plan_dependencies(root, config, *, enabled=False):
    """Freeze every existing distribution. Solver conflicts stop; no upgrade fallback."""
    if not enabled:
        raise RuntimeError("Dependency planning disabled")
    root = Path(root)
    dest = root / "work/setup"
    dest.mkdir(parents=True, exist_ok=True)
    versions = installed_versions()
    for name, expected in config["dependencies"]["preserve_reported"].items():
        actual = metadata.version(name)
        if actual.split("+")[0] != expected:
            raise RuntimeError(f"Reported {name}={expected}, actual={actual}; record and return for review")
    constraints = dest / "preserve-installed.txt"
    constraints.write_text("".join(f"{name}=={version}\n" for name, version in sorted(versions.items())))
    cmd = [sys.executable, "-m", "pip", "install", "--dry-run", "--report", str(dest / "plan.json"),
           "--constraint", str(constraints), *config["dependencies"]["proposed_not_runtime_tested"]]
    result = subprocess.run(cmd, text=True, capture_output=True)
    (dest / "solver.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("Pinned setup plan conflicts; return work/setup/solver.log for review")
    plan = json.loads((dest / "plan.json").read_text())
    proposed = [f"{e['metadata']['name']}=={e['metadata']['version']}" for e in plan.get("install", [])]
    existing = {name.casefold().replace("_", "-") for name in versions}
    if any(s.split("==")[0].casefold().replace("_", "-") in existing for s in proposed):
        raise RuntimeError("Plan would replace an installed distribution; stop for review")
    atomic_json(dest / "review-plan.json", {"installed": versions, "install_exact": proposed,
                                          "plan_sha256": file_hash(dest / "plan.json")})
    return proposed


def install_planned(root, *, enabled=False, reviewed_plan_sha256=None):
    if not enabled:
        raise RuntimeError("Installation disabled")
    dest = Path(root) / "work/setup"
    reviewed = json.loads((dest / "review-plan.json").read_text())
    if (not reviewed_plan_sha256 or reviewed_plan_sha256 != file_hash(dest / "plan.json")
            or reviewed_plan_sha256 != reviewed["plan_sha256"]):
        raise RuntimeError("Exact reviewed plan hash required")
    if installed_versions() != reviewed["installed"]:
        raise RuntimeError("Environment changed since plan; return for review")
    packages = reviewed["install_exact"]
    if packages:
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", *packages], check=True)
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    return packages
