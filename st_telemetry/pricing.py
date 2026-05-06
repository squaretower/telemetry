"""Modal compute pricing, $/hour.

Sourced from modal.com/pricing. Treat as estimates — Modal's invoice is
authoritative. Override via ST_TELEMETRY_PRICING env var (JSON) if needed.
"""
from __future__ import annotations
import json
import os
from typing import Optional

# GPU pricing in USD/hour. Keys are normalized GPU names (uppercase, no suffix).
GPU_PRICING: dict[str, float] = {
    "T4": 0.59,
    "L4": 0.80,
    "A10G": 1.10,
    "L40S": 1.95,
    "A100": 3.40,         # 40GB
    "A100-40GB": 3.40,
    "A100-80GB": 4.56,
    "H100": 8.20,
    "H200": 10.50,
    "B200": 14.00,
}

# Per-core CPU and per-GiB memory rates ($/hour) when no GPU is attached,
# or as additive when GPU is present (Modal bundles, but we approximate).
CPU_PER_CORE_HOUR = 0.135
MEMORY_PER_GIB_HOUR = 0.024

PRICING = {
    "gpu": GPU_PRICING,
    "cpu_per_core_hour": CPU_PER_CORE_HOUR,
    "memory_per_gib_hour": MEMORY_PER_GIB_HOUR,
}

_overrides = os.environ.get("ST_TELEMETRY_PRICING")
if _overrides:
    try:
        _o = json.loads(_overrides)
        GPU_PRICING.update(_o.get("gpu", {}))
    except (json.JSONDecodeError, TypeError):
        pass


def normalize_gpu(gpu: object) -> tuple[Optional[str], int]:
    """Modal accepts gpu as str ('A100'), 'A100:2', or modal.gpu.* objects.

    Returns (normalized_name, count). (None, 0) if no GPU.
    """
    if gpu is None or gpu is False:
        return None, 0
    if isinstance(gpu, str):
        s = gpu.upper().strip()
        count = 1
        if ":" in s:
            s, c = s.split(":", 1)
            try:
                count = int(c)
            except ValueError:
                count = 1
        return s, count
    # modal.gpu.A100(count=N) etc — best-effort introspection
    name = type(gpu).__name__.upper()
    count = getattr(gpu, "count", 1) or 1
    return name, count


def estimate_cost(
    duration_s: float,
    gpu: object = None,
    cpu: Optional[float] = None,
    memory_mb: Optional[int] = None,
) -> dict:
    """Return cost breakdown in USD for a workload of given duration/shape."""
    hours = duration_s / 3600.0
    gpu_name, gpu_count = normalize_gpu(gpu)
    gpu_rate = GPU_PRICING.get(gpu_name, 0.0) if gpu_name else 0.0
    gpu_cost = gpu_rate * gpu_count * hours
    cpu_cost = (cpu or 0.0) * CPU_PER_CORE_HOUR * hours
    mem_cost = ((memory_mb or 0) / 1024.0) * MEMORY_PER_GIB_HOUR * hours
    return {
        "gpu_name": gpu_name,
        "gpu_count": gpu_count,
        "gpu_rate_per_hour": gpu_rate,
        "gpu_cost_usd": round(gpu_cost, 6),
        "cpu_cost_usd": round(cpu_cost, 6),
        "memory_cost_usd": round(mem_cost, 6),
        "total_cost_usd": round(gpu_cost + cpu_cost + mem_cost, 6),
    }
