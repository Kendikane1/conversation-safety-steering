# CPU reproduction notebooks

Use Python3.9 or later with a local Jupyter kernel, or a CPU Colab runtime. The recorded W03H run used Python3.13.18 on Linux. Analysis modules use only Python's standard library; Colab's optional file-upload picker is provided by Colab. No package installation, Drive mount, model download, training or inference is part of either notebook.

| Notebook | Inputs | Scope |
|---|---|---|
| [W03H source](W03H_CPU_REPRODUCE.ipynb) | [Reviewed W03H bundle](reproduction-inputs-w03h-v1.zip) | Seven stages: hashes, context coverage, observed/primary outcomes, eight main family-weighted paired contrasts, logical bounds and changed IDs |
| [Historical/RF128 recovery-v2 source](STUDIES_CPU_REPRODUCE_V2.ipynb) | [Reviewed historical/RF v2 bundle](reproduction-inputs-studies-v2.zip) | Eight stages: native historical phases, W02 replay table, six-cap C/G coverage, separately flagged retrospective sensitivity, RF counts/routes and eight contrasts with registered/finite-frame bounds |

Run one numbered cell at a time and inspect the output. Set DATA_ROOT explicitly or upload the exact matching ZIP. Hashes are checked before loading code. If a cell fails, stop and retain the error; do not skip it or change inputs to make an assertion pass. After completion, save both the JSON and notebook, reopen the notebook and inspect stored outputs. Restart at cell1 when changing runtime; do not rely on a foreign cached module.

The [edited actual W03H executed copy](W03H_CPU_REPRODUCE.executed.ipynb), [public JSON result](w03h-public-reproduction.json) and [cell provenance](W03H_CPU_EXECUTION_PROVENANCE.json) preserve its completed CPU run. The original saved notebook has null execution counts after Colab reload; these are preserved rather than invented. Personal runtime metadata and the uploader rich display are removed, scientific streams and code are unchanged. The corrected initial ZIP selection is disclosed in the saved note; the unavailable earlier error is not reconstructed.

The W03H bundle's ten study files match the final evidence export exactly. Its original global redaction manifest covers W03H only; the final dataset's manifest covers all studies. The historical/RF bundle was built from the frozen final evidence snapshot. These ZIPs preserve the exact inputs used by their respective CPU notebooks even if additional release documentation changes later.

These runs recompute arithmetic over reviewed exports. They do not repeat generation, independently validate labels, retokenize redacted text to recover original lengths, or establish human validation. W03H main responder contrasts are eight explicitly defined comparisons; the notebook does not claim to reconstruct every secondary historical contrast. Frame and missing-outcome bounds are reported with their own assumptions and are not interchangeable with sampling confidence intervals.

## Preserved interrupted v1 run

The [actual v1 interrupted notebook](STUDIES_V1_INTERRUPTED_CPU_REPRODUCE.executed.ipynb) retains its stage3 assertion failure: the initial adapter omitted four allowed W01D anchors with branch=null, despite their original allow policy labels. Setup and hash verification passed; later stages were not executed. [Cell provenance](STUDIES_V1_INTERRUPTED_CPU_EXECUTION_PROVENANCE.json) records the edited public copy. The [original v1 source](STUDIES_CPU_REPRODUCE.ipynb) and [v1 inputs](reproduction-inputs-studies-v1.zip) remain preserved for audit, not recommended as a successful reproduction.

V2 uses original policy labels when branch is null, rejects contradictions, and uses a distinct directory/manifest/ZIP. Its full17cells are intended to be appended after the original17cells, preserving the failed output. Actual v2 execution is pending. This is an analysis-adapter correction, not relabelling or a new model run.
