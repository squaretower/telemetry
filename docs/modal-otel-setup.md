# One-time Modal OTel setup

Modal exports per-container metrics natively. We do **not** reimplement
this — we just turn it on and point it at our collector.

## What Modal exports

Tagged with `container_id`, `function_name`, `function_id`, `app_name`,
`app_id`, `workspace_name`, `workspace_id`:

- `modal.gpu.compute.utilization`
- `modal.gpu.memory.usage`
- `modal.cpu.utilization`
- `modal.memory.usage`
- `modal.container.running`
- `modal.input_events.elapsed_time_us` — execution time
- `modal.input_events.input_queue_time_us` — **queue/scheduling delay**
- `modal.input_events.cold_start_time_us` — **cold start cost**
- `modal.input_events.total_inputs`, success/failure counters

The queue-time and cold-start metrics are the headline signals for
burst/queueability analysis. That's why this matters more than anything
we'd build ourselves.

## Setup (~5 minutes, done once per workspace)

1. Modal dashboard → Workspace settings → Integrations → OpenTelemetry.
2. Provide the OTLP/HTTP endpoint of our collector and any auth header.
3. Save. Modal starts pushing metrics within a minute.

That's the entire integration. Nothing changes in the customer's code.

## Joining OTel metrics to billing

The OTel metrics carry `app_name` / `function_name`. Modal's billing
report carries `app_name` and the tags we set via `st_telemetry.tag(...)`
(gpu, workload_type, experiment_id, etc.). Joining on `app_name` +
time-bucket gives the full picture: cost (from billing) ⨝ utilization /
queue / cold-start (from OTel) ⨝ shape (from our tags).

GPU type specifically is **not** in either Modal stream — it only lives
in our tags. That's the gap `st_telemetry.tag()` fills.

## Plan tier note

- App tagging + billing report API: **Team or Enterprise**.
- Native OTel export: check current Modal docs; historically Team+.
- If the customer is on Starter, the fallback is the dashboard's invoice
  view (monthly totals only) and we have no run-level granularity until
  they upgrade.
