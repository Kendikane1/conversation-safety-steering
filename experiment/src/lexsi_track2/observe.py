"""Removable pass-through observation of an existing CAST instance."""
from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def observe_cast(cast):
    """Capture the exact gate return consumed by generate and actual hook calls.

    No score is recalculated. The original hook's result is returned unchanged.
    This is single-threaded and supports the assignment's batch size one only.
    """
    if cast._handles or cast._row_mask is not None:
        raise RuntimeError("Dirty intervention state at endpoint boundary")
    gate = cast._gate_fires
    factory = cast._make_steering_hook
    trace = {"gate_calls": [], "intervention_calls": 0, "intervention_shapes": []}
    saved = {name: cast.__dict__.get(name) for name in ("_gate_fires", "_make_steering_hook")}
    present = {name: name in cast.__dict__ for name in saved}

    def observed_gate(*args, **kwargs):
        result = gate(*args, **kwargs)
        fires, scores = result
        if not isinstance(fires, list) or not isinstance(scores, list) or len(fires) != 1 or len(scores) != 1:
            raise RuntimeError("Missing hook or unexpected CAST batch result; evidence invalid")
        trace["gate_calls"].append({"decision": bool(fires[0]), "raw_score": float(scores[0])})
        return result

    def observed_factory(vector):
        hook = factory(vector)

        def observer(module, inputs, output):
            result = hook(module, inputs, output)
            h = result[0] if isinstance(result, tuple) else result
            trace["intervention_calls"] += 1
            shape = list(h.shape)
            if shape not in trace["intervention_shapes"]:
                trace["intervention_shapes"].append(shape)
            return result
        return observer

    cast._gate_fires = observed_gate
    cast._make_steering_hook = observed_factory
    try:
        yield trace
    finally:
        cast.remove()
        cast._row_mask = None
        for name in saved:
            if present[name]:
                setattr(cast, name, saved[name])
            else:
                cast.__dict__.pop(name, None)
        if cast._handles:
            raise RuntimeError("CAST hooks remain after cleanup")


def generate_arm(model, cast, arm, inputs, generation):
    if inputs["input_ids"].shape[0] != 1:
        raise ValueError("Only batch size one is supported")
    with observe_cast(cast) as trace:
        if arm == "base":
            result = model.generate(**inputs, **generation)
        elif arm == "conditional":
            result = cast.generate(**inputs, **generation)
        elif arm == "always_on":
            # Same CAST behavior hooks, vector, layers and alpha; no gate call.
            cast.install()
            result = model.generate(**inputs, **generation)
        else:
            raise ValueError(f"Unknown arm {arm}")
    calls = trace["gate_calls"]
    if len(calls) != (1 if arm == "conditional" else 0):
        raise RuntimeError("Conditional route did not observe exactly one decision")
    expected = arm == "always_on" or (arm == "conditional" and calls[0]["decision"])
    if bool(trace["intervention_calls"]) != expected:
        raise RuntimeError("Actual behavior-hook execution disagrees with requested arm/gate")
    trace["actual_intervention"] = bool(trace["intervention_calls"])
    return result, trace
