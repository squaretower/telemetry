"""Thin NVML wrapper. All calls are best-effort — never raise into user code."""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

try:
    import pynvml  # nvidia-ml-py
    _NVML_AVAILABLE = True
except ImportError:
    _NVML_AVAILABLE = False


@dataclass
class GpuStatic:
    """Snapshot taken once at container start."""
    count: int = 0
    name: Optional[str] = None      # canonical model, e.g. "NVIDIA H100 80GB HBM3"
    memory_total_mb: int = 0
    driver_version: Optional[str] = None


@dataclass
class GpuAggregate:
    """Per-GPU integrated stats over the sampling window."""
    util_seconds: float = 0.0       # ∫(utilization%/100)·dt — proxy for actual GPU work
    memory_peak_mb: int = 0
    samples: int = 0


@dataclass
class GpuTelemetry:
    static: GpuStatic = field(default_factory=GpuStatic)
    per_gpu: list[GpuAggregate] = field(default_factory=list)

    def total_util_seconds(self) -> float:
        return sum(g.util_seconds for g in self.per_gpu)


def _nvml_init() -> bool:
    if not _NVML_AVAILABLE:
        return False
    try:
        pynvml.nvmlInit()
        return True
    except Exception as e:
        log.debug("NVML init failed: %s", e)
        return False


def snapshot_static() -> GpuStatic:
    """Read GPU model/count once. Returns empty struct on CPU-only containers."""
    if not _nvml_init():
        return GpuStatic()
    try:
        count = pynvml.nvmlDeviceGetCount()
        if count == 0:
            return GpuStatic()
        h0 = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h0)
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        mem = pynvml.nvmlDeviceGetMemoryInfo(h0).total // (1024 * 1024)
        try:
            drv = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(drv, bytes):
                drv = drv.decode("utf-8", "replace")
        except Exception:
            drv = None
        return GpuStatic(count=count, name=name, memory_total_mb=mem, driver_version=drv)
    except Exception as e:
        log.debug("NVML static snapshot failed: %s", e)
        return GpuStatic()


class GpuSampler:
    """Background thread that integrates utilization over wall-clock time."""

    def __init__(self, interval_s: float = 1.0):
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.telemetry = GpuTelemetry()

    def start(self) -> None:
        self.telemetry.static = snapshot_static()
        n = self.telemetry.static.count
        if n == 0:
            return
        self.telemetry.per_gpu = [GpuAggregate() for _ in range(n)]
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> GpuTelemetry:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s + 1.0)
        return self.telemetry

    def _loop(self) -> None:
        n = self.telemetry.static.count
        handles = []
        try:
            handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(n)]
        except Exception:
            return
        last = time.monotonic()
        while not self._stop.wait(self.interval_s):
            now = time.monotonic()
            dt = now - last
            last = now
            for i, h in enumerate(handles):
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu  # 0..100
                    mem = pynvml.nvmlDeviceGetMemoryInfo(h).used // (1024 * 1024)
                    agg = self.telemetry.per_gpu[i]
                    agg.util_seconds += (util / 100.0) * dt
                    agg.memory_peak_mb = max(agg.memory_peak_mb, mem)
                    agg.samples += 1
                except Exception:
                    pass
