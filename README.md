# st-telemetry

Workload telemetry for Modal AI/RL jobs. Built so it works on **every
Modal plan including Starter / free** — telemetry is captured from inside
the container and shipped directly to Squaretower's OTLP collector. We
don't depend on Modal's billing API or native OTel integration (those are
gated behind Team/Enterprise).

## How it works

Three layers, in order of importance:

1. **`@track` decorator (in-container).** Reads GPU model/count/memory
   from NVML, samples GPU utilization at 1 Hz to compute GPU-seconds,
   times the call, captures Modal's `function_call_id` / `task_id`, and
   ships one OTLP span per call to `ST_TELEMETRY_ENDPOINT`. Plan-tier
   independent. This is the workhorse.
2. **`register_workload(...)` (declarative).** Workload metadata —
   workload_type, experiment_id, interruptible.
   Stashed at module level, read by `@track`, lands on every span as
   `workload.*` attributes. Plan-tier independent. Optional helper
   `apply_modal_tags(app)` (called inside `local_entrypoint`) also pushes
   the same metadata to Modal's billing report on Team/Enterprise.
3. **`pull_billing(...)` (server-side).** Wraps `modal billing report`
   for the Team/Enterprise case where we want to reconcile our measured
   GPU-seconds against Modal's invoiced cost.

## What we capture per call

- `gpu.name`, `gpu.count`, `gpu.memory_total_mb`, `gpu.driver_version`
  (ground truth from NVML — does not depend on what the agent declared)
- `gpu.util_seconds_total` and per-device `gpu.<i>.util_seconds`
  (∫utilization·dt — honest measure of GPU work done)
- `gpu.<i>.memory_peak_mb`
- `duration_s`
- `modal.function_call_id`, `modal.input_id`, `modal.task_id`, `modal.app_id`
- All `tag()` metadata as span attributes

Cost computation is done in our backend from `gpu.name` + `gpu.util_seconds`
+ Modal's published rate card — keeps the client dumb and avoids drift.

## Install

```bash
pip install git+https://github.com/squaretower/telemetry.git
```

Inside Modal images:

```python
image = modal.Image.debian_slim().pip_install(
    "git+https://github.com/squaretower/telemetry.git",
)
```

## Customer-side setup (one time)

```bash
modal secret create squaretower-telemetry \
    ST_TELEMETRY_ENDPOINT=https://telemetry.squaretower.com \
    ST_TELEMETRY_API_KEY=<token>
```

Each `@app.function(...)` then attaches `secrets=[modal.Secret.from_name("squaretower-telemetry")]`.

## Agent-side usage

See `SKILL.md`. The agent adds: one import, one decorator (`@track`),
one tagging call (`tag(app, ...)`), and the secret on the function.

## Cold-start gap

`@track` runs *inside* the container, so the clock starts after import
and Modal's runtime startup. True cold-start time is therefore not
captured by `@track`. On Team/Enterprise we backfill it from Modal's
native OTel `modal.input_events.cold_start_time_us` metric (see
`docs/modal-otel-setup.md`). On Starter, this is a known gap.

## Plan tier matrix

| Capability | Starter | Team / Enterprise |
| --- | --- | --- |
| `@track` GPU + duration spans | ✅ | ✅ |
| `tag()` metadata on spans | ✅ | ✅ |
| `tag()` on Modal billing report | ❌ (dropped) | ✅ |
| `pull_billing()` server-side reconciliation | ❌ | ✅ |
| Native Modal OTel cold-start metric | ❌ | ✅ |

## Roadmap

- Container-import-time hook to estimate cold-start from inside.
- Prime Intellect (Lab + Compute) — different architecture; instrument
  at orchestration boundary, not per-function.
- Demand-shape analyzer over collected spans.
