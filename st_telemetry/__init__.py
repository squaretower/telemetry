"""st-telemetry: agent-side instrumentation for Modal workloads.

Three things:

1. `@track` — function decorator. Runs inside the Modal container, reads
   GPU info via NVML, samples utilization, and ships an OTLP span to
   Squaretower's collector when the function exits. Works on every Modal
   plan, including Starter / free, because it doesn't depend on Modal's
   billing API or native OTel integration.

2. `tag(app, ...)` — adds App tags for Modal's billing report join. No-op
   on Starter (Modal silently drops tags), high-value on Team/Enterprise.

3. `pull_billing(...)` — server-side helper to pull `modal billing report`
   with our tags. Run by us, not the agent. Team/Enterprise only.
"""
from .tagging import register_workload, apply_modal_tags, WorkloadKind
from .tracker import track
from .billing import pull_billing

__all__ = [
    "track",
    "register_workload",
    "apply_modal_tags",
    "WorkloadKind",
    "pull_billing",
]
