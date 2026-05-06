"""Pull Modal billing data with our tags joined.

Wraps `modal billing report --csv --tag-names ...`. Requires Team or
Enterprise plan — Starter doesn't expose the billing CLI.
"""
from __future__ import annotations
import csv
import io
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

# Tag names we emit from `tag()`. Pulling these makes them appear as
# columns in the report.
DEFAULT_TAG_NAMES = (
    "gpu",
    "workload_type",
    "experiment_id",
    "model",
    "cpu",
    "memory_mb",
    "interruptible",
    "st_workload_id",
)


@dataclass
class BillingRow:
    interval_start: str
    app_name: str
    cost_usd: float
    tags: dict[str, str]


def pull_billing(
    start: date,
    end: date,
    resolution: str = "h",
    tag_names: Optional[Iterable[str]] = None,
) -> list[BillingRow]:
    """Run `modal billing report` and parse the CSV.

    Args:
        start, end: inclusive date range.
        resolution: 'h' (hourly) or 'd' (daily).
        tag_names: tags to include as columns. Defaults to the keys we set
            in `tag()`.

    Returns parsed rows. Raises `RuntimeError` if the CLI is unavailable
    (likely a plan-tier issue).
    """
    tag_names = list(tag_names or DEFAULT_TAG_NAMES)
    cmd = [
        "modal", "billing", "report",
        "--start", start.isoformat(),
        "--end", end.isoformat(),
        "--resolution", resolution,
        "--csv",
    ]
    for t in tag_names:
        cmd += ["--tag-names", t]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"modal billing report failed (exit {proc.returncode}). "
            f"This API requires Team or Enterprise plan.\nstderr: {proc.stderr}"
        )

    reader = csv.DictReader(io.StringIO(proc.stdout))
    rows: list[BillingRow] = []
    for r in reader:
        # Modal's CSV columns aren't formally documented; we defensively
        # pull common-looking keys and route the rest into `tags`.
        interval = r.get("interval_start") or r.get("start") or r.get("time") or ""
        app_name = r.get("app_name") or r.get("app") or ""
        cost_str = r.get("cost") or r.get("cost_usd") or "0"
        try:
            cost = float(cost_str)
        except ValueError:
            cost = 0.0
        tags = {k: v for k, v in r.items() if k in tag_names and v}
        rows.append(BillingRow(interval, app_name, cost, tags))
    return rows
