"""Reference instrumented Modal script."""
import modal
from st_telemetry import register_workload, track

image = modal.Image.debian_slim().pip_install(
    "git+https://github.com/squaretower/telemetry.git",
    "torch",
)

app = modal.App("rl-ppo-cartpole")

register_workload(
    gpu="H100",
    workload_type="rl_rollout",
    experiment_id="ppo-cartpole-2026-05-05-seed42",
    model="qwen-2.5-7b",
    interruptible=True,
)


@app.function(
    image=image,
    gpu="H100",
    cpu=8.0,
    memory=65536,
    timeout=7200,
    secrets=[modal.Secret.from_name("squaretower-telemetry")],
)
@track
def train(seed: int) -> dict:
    return {"seed": seed, "reward": 0.0}


@app.local_entrypoint()
def main():
    print(train.remote(42))
