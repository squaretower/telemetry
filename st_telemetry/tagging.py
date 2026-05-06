"""Workload metadata registration.

The agent calls `register_workload(...)` once at module top level. The
metadata gets stashed in a module-level dict and read by `@track` when
emitting spans, so it lands on every span the workload produces — without
depending on Modal's `App.set_tags` (which only works while the app is
running, and is silently dropped on Starter plans anyway).

For Team/Enterprise customers who *also* want this metadata in the Modal
billing report, call `apply_modal_tags(app)` from inside a
`@app.local_entrypoint()` or function. Optional.
"""
from __future__ import annotations
import os
import time
import uuid
from typing import Any, Literal, Optional

WorkloadKind = Literal[
    "training",
    "inference",
    "rl_rollout",
    "evaluation",
    "qa_eval",
    "data_processing",
    "other",
]

REQUIRED = ("gpu", "workload_type", "experiment_id")

# Module-level stash. Process-global; one workload registration per script,
# which matches how Modal scripts are structured (one App per file).
_WORKLOAD: dict[str, str] = {}


def register_workload(
    *,
    gpu: Optional[str],
    workload_type: WorkloadKind,
    experiment_id: str,
    model: Optional[str] = None,
    cpu: Optional[float] = None,
    memory_mb: Optional[int] = None,
    interruptible: Optional[bool] = None,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Stash workload metadata. Read by `@track` for every emitted span.

    Args mirror the previous `tag()` signature; see SKILL.md for guidance.
    """
    tags: dict[str, str] = {
        "gpu_declared": gpu if gpu is not None else "none",
        "workload_type": workload_type,
        "experiment_id": experiment_id,
        "st_workload_id": str(uuid.uuid4()),
        "st_registered_at": str(int(time.time())),
        "st_user": os.environ.get("MODAL_USER") or os.environ.get("USER", "unknown"),
    }
    if model is not None:
        tags["model"] = model
    if cpu is not None:
        tags["cpu_declared"] = str(cpu)
    if memory_mb is not None:
        tags["memory_mb_declared"] = str(memory_mb)
    if interruptible is not None:
        tags["interruptible"] = str(bool(interruptible)).lower()
    if extra:
        tags.update({k: str(v) for k, v in extra.items()})

    missing = [k for k in REQUIRED if (k != "gpu" and not tags.get(k.replace("gpu", "gpu_declared"), ""))
               or (k == "gpu" and "gpu_declared" not in tags)]
    # Simpler: just enforce the inputs.
    if workload_type is None or not experiment_id:
        raise ValueError(
            "register_workload() requires workload_type and experiment_id."
        )

    _WORKLOAD.clear()
    _WORKLOAD.update(tags)
    return dict(tags)


def get_workload() -> dict[str, str]:
    """Read the registered metadata. Empty dict if not registered."""
    return dict(_WORKLOAD)


def apply_modal_tags(app: Any) -> None:
    """Optional: copy registered metadata into Modal's App tags so it
    flows into the billing report. Must be called *while the app is
    running* — typically inside a `@app.local_entrypoint()` or function.

    No-op on Starter plans (Modal silently drops). Safe to call
    unconditionally — errors are swallowed so this never breaks user code.
    """
    if not _WORKLOAD:
        return
    set_tags = getattr(app, "set_tags", None)
    if set_tags is None:
        return
    try:
        set_tags(_WORKLOAD)
    except Exception:
        pass
