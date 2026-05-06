"""End-to-end smoketest on a real Modal CPU function (free plan)."""
import os
import modal
from st_telemetry import track, register_workload

image = modal.Image.debian_slim().pip_install(
    "git+https://github.com/squaretower/telemetry.git",
)

app = modal.App("st-telemetry-smoketest")

register_workload(
    gpu=None,
    workload_type="other",
    experiment_id="smoketest-cpu-2026-05-05",
    interruptible=True,
)


@app.function(image=image, cpu=1.0, memory=512, timeout=120)
@track
def cpu_workload(n: int) -> int:
    import time
    time.sleep(2)
    return sum(range(n))


@app.local_entrypoint()
def main():
    os.environ.setdefault("ST_TELEMETRY_CONSOLE", "1")
    print(f"result = {cpu_workload.remote(1000)}")
