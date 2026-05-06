"""End-to-end GPU smoketest. Allocates a T4 (cheapest Modal GPU at ~$0.59/hr),
spins it under torch matmul for ~30s to drive utilization above zero, and
emits one span. Total cost per run ≈ $0.005.

Run:
    modal run examples/smoketest_gpu.py

Then check SigNoz UI for span `modal.fn:gpu_workload` with attributes:
    gpu.name             = "Tesla T4" (NVML ground truth)
    gpu.count            = 1
    gpu.util_seconds_total ~ 25-30 (most of the wall clock at high util)
    duration_s           ~ 30
    workload.gpu         = "T4"        (what we declared)
    workload.workload_type = "training"
"""
import modal
from st_telemetry import track, register_workload

image = modal.Image.debian_slim().pip_install(
    "git+https://github.com/squaretower/telemetry.git",
    "torch",
)

app = modal.App("st-telemetry-gpu-smoketest")

register_workload(
    gpu="T4",
    workload_type="training",
    experiment_id="smoketest-gpu-2026-05-06",
    model="synthetic-matmul",
    interruptible=True,
)


@app.function(
    image=image,
    gpu="T4",
    timeout=180,
    secrets=[modal.Secret.from_name("squaretower-telemetry")],
)
@track
def gpu_workload(seconds: int = 30) -> dict:
    import time
    import torch

    assert torch.cuda.is_available(), "no CUDA visible inside container"
    device = torch.device("cuda")
    a = torch.randn(4096, 4096, device=device)
    b = torch.randn(4096, 4096, device=device)

    start = time.time()
    iters = 0
    while time.time() - start < seconds:
        a = a @ b
        torch.cuda.synchronize()
        iters += 1

    return {
        "iters": iters,
        "elapsed_s": round(time.time() - start, 2),
        "device_name": torch.cuda.get_device_name(0),
    }


@app.local_entrypoint()
def main():
    print(gpu_workload.remote(30))
