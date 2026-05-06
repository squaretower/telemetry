# Modal workload telemetry (Squaretower)

When you write or modify a Modal script in this project, instrument it
with `st-telemetry`. Works on **every Modal plan including free /
Starter** — telemetry is captured from inside the container and shipped
directly to Squaretower's collector. Modal's billing API and native OTel
integration are not required.

## Before you write code: confirm the Modal Secret exists

The instrumented script will reference a Modal Secret named
`squaretower-telemetry`. Check that it exists *before* writing the
script:

```bash
modal secret list | grep squaretower-telemetry
```

If it's missing, **stop and ask the user to create it** with their
Squaretower OTLP endpoint and API key:

```bash
modal secret create squaretower-telemetry \
    ST_TELEMETRY_ENDPOINT=https://otel.<their-squaretower-host> \
    ST_TELEMETRY_API_KEY=<their-token>
```

Do not invent placeholder values, do not run the create command
yourself, and do not skip the secret on the function decorator. Without
the secret, telemetry silently falls back to console output and never
reaches Squaretower.

## What you must add

Three things, all small.

### 1. Install `st-telemetry` in the function image

```python
image = modal.Image.debian_slim().pip_install(
    "git+https://github.com/squaretower/telemetry.git",
    "torch", "gymnasium",            # whatever the workload needs
)
```

`st-telemetry` installs from a public GitHub repo. Its dependencies
(`opentelemetry-*`, `nvidia-ml-py`) come along automatically — don't
list them yourself.

### 2. Register workload metadata at module top level

```python
from st_telemetry import register_workload

register_workload(
    gpu="H100",
    workload_type="rl_rollout",
    experiment_id="ppo-cartpole-2026-05-05-seed42",
    interruptible=True,
)
```

Call this **once per script, at module top level** (not inside a
function). It runs both locally and inside the container — that's how
the metadata reaches the spans.

### 3. Decorate the function with `@track` (innermost)

```python
from st_telemetry import track

@app.function(
    image=image,
    gpu="H100",
    cpu=8.0,
    memory=65536,
    secrets=[modal.Secret.from_name("squaretower-telemetry")],
)
@track
def train(seed: int):
    ...
```

`@track` goes **below** `@app.function` (it wraps the function body that
runs in the container). Order matters — get this wrong and Modal will
register the unwrapped function.

The Modal Secret carries `ST_TELEMETRY_ENDPOINT` and
`ST_TELEMETRY_API_KEY`. The customer creates it once via
`modal secret create squaretower-telemetry ST_TELEMETRY_ENDPOINT=... ST_TELEMETRY_API_KEY=...`.
You attach it to every function decorator.

## Full template

```python
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
    experiment_id="ppo-cartpole-2026-05-05",
    interruptible=True,
)

@app.function(
    image=image,
    gpu="H100",
    cpu=8.0,
    memory=65536,
    secrets=[modal.Secret.from_name("squaretower-telemetry")],
    timeout=7200,
)
@track
def train(seed: int) -> dict:
    ...
    return {"seed": seed, "reward": ...}

@app.local_entrypoint()
def main():
    print(list(train.map(range(16))))
```

## What gets captured per `.remote()` call

From inside the container, with no Modal-tier dependency:

- **GPU ground truth (NVML)**: `gpu.name` (real model string, e.g.
  `"NVIDIA H100 80GB HBM3"`), `gpu.count`, `gpu.memory_total_mb`,
  `gpu.driver_version`.
- **GPU-seconds**: `gpu.util_seconds_total` and per-device
  `gpu.<i>.util_seconds`. Computed as ∫(utilization·dt) at 1 Hz.
- **Memory peak**: `gpu.<i>.memory_peak_mb`.
- **Wall-clock**: `duration_s`.
- **Modal IDs**: `modal.function_call_id`, `modal.input_id`,
  `modal.task_id`, `modal.app_id` — the join keys for any later
  reconciliation against Modal's billing report.
- **All `register_workload(...)` metadata** as `workload.*` attributes.

## Required fields on `register_workload()`

- `gpu` — string from `@app.function(gpu=...)`. Pass `None` for CPU-only.
  This is what the *agent declared*. NVML-observed GPU is captured
  separately as `gpu.name` and is the source of truth.
- `workload_type` — `"training"`, `"inference"`, `"rl_rollout"`,
  `"evaluation"`, `"qa_eval"`, `"data_processing"`, or `"other"`.
- `experiment_id` — stable slug. Reuse across retries / resumes / stages
  of the same logical experiment so calls group.

## High-value optional fields

- `interruptible` — bool. Drives spot eligibility.
- `model` — e.g. `"qwen-2.5-7b"`.
- `cpu`, `memory_mb` — only if explicitly set in the decorator (don't
  fabricate Modal defaults).

## Things to NOT do

- Do not wrap or replace `modal.App`. Don't subclass it.
- Do not call `app.set_tags(...)` directly — it errors at module
  top-level (the App isn't running yet) and is silently dropped on
  Starter anyway.
- Do not add manual OpenTelemetry spans, exporters, or tracer setup.
  `@track` configures everything.
- Do not put `@track` above `@app.function` — it has to be the inner
  decorator.
- Do not instrument helper functions called by the tracked function.
  Granularity is per Modal-function-call, not per Python-function-call.
- Do not pass `gpu=None` to `register_workload()` as a placeholder when
  the workload *does* use a GPU. Read your own `@app.function(gpu=...)`
  and pass it.

## What you should reason about before writing the script

You (the agent) are about to choose `gpu=`, `cpu=`, `memory=`, and the
kind of work being done. That information is in your own context — bake
it into `register_workload()` *as you write the file*. If you can't
name the GPU you just chose, re-read the decorator before calling
`register_workload()`.

For `experiment_id`, prefer intent-encoded slugs
(`"ppo-halfcheetah-lr-sweep-2026-05-05"`) over timestamp blobs. If the
user named the experiment in their request, use that name.
