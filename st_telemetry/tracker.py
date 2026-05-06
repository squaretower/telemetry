"""@track decorator — the in-container instrumentation.

Goals:
  - Capture GPU type/count from NVML (ground truth, plan-tier-independent).
  - Capture wall-clock duration and GPU-seconds (∫util·dt).
  - Capture Modal IDs (function_call, input, task) for downstream joins.
  - Emit one OTLP span per call. Flush before returning so the container
    can die without losing data.
  - Never crash user code: every telemetry path is best-effort.
"""
from __future__ import annotations
import functools
import logging
import os
import time
from typing import Any, Callable

from opentelemetry.trace import Status, StatusCode

from .exporter import get_tracer, force_flush
from .gpu import GpuSampler
from .tagging import get_workload

log = logging.getLogger(__name__)


def _modal_ids() -> dict[str, str]:
    """Best-effort Modal context. Modal's API surface for these has shifted
    over versions, so we try a couple of paths and tolerate failure."""
    out: dict[str, str] = {}
    try:
        import modal
        for attr, key in (
            ("current_function_call_id", "modal.function_call_id"),
            ("current_input_id", "modal.input_id"),
        ):
            fn = getattr(modal, attr, None)
            if callable(fn):
                try:
                    v = fn()
                    if v:
                        out[key] = str(v)
                except Exception:
                    pass
    except ImportError:
        pass
    if v := os.environ.get("MODAL_TASK_ID"):
        out["modal.task_id"] = v
    if v := os.environ.get("MODAL_APP_ID"):
        out["modal.app_id"] = v
    return out


def track(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator. Apply *innermost* — i.e. closest to the user's function:

        @app.function(gpu="H100", secrets=[...])
        @track
        def train(...): ...
    """
    func_name = getattr(fn, "__name__", "anonymous")

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        tracer = get_tracer()
        sampler = GpuSampler(interval_s=1.0)
        sampler.start()
        start = time.time()
        with tracer.start_as_current_span(f"modal.fn:{func_name}") as span:
            span.set_attribute("modal.function", func_name)
            for k, v in _modal_ids().items():
                span.set_attribute(k, v)
            for k, v in get_workload().items():
                span.set_attribute(f"workload.{k}", v)
            try:
                result = fn(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
            finally:
                duration = time.time() - start
                tele = sampler.stop()
                span.set_attribute("duration_s", duration)
                if tele.static.count > 0:
                    span.set_attribute("gpu.name", tele.static.name or "unknown")
                    span.set_attribute("gpu.count", tele.static.count)
                    span.set_attribute("gpu.memory_total_mb", tele.static.memory_total_mb)
                    if tele.static.driver_version:
                        span.set_attribute("gpu.driver_version", tele.static.driver_version)
                    span.set_attribute("gpu.util_seconds_total", tele.total_util_seconds())
                    for i, agg in enumerate(tele.per_gpu):
                        span.set_attribute(f"gpu.{i}.util_seconds", agg.util_seconds)
                        span.set_attribute(f"gpu.{i}.memory_peak_mb", agg.memory_peak_mb)
                else:
                    span.set_attribute("gpu.count", 0)
                try:
                    force_flush(timeout_ms=5000)
                except Exception as e:
                    log.debug("flush failed: %s", e)
    return wrapper
