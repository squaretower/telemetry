"""OTLP/HTTP tracer setup pointed at Squaretower's collector.

Reads:
  ST_TELEMETRY_ENDPOINT   — collector URL, e.g. https://telemetry.squaretower.com
                            (with no path; we append /v1/traces)
  ST_TELEMETRY_API_KEY    — bearer token for auth
  ST_TELEMETRY_CONSOLE=1  — also print spans to stdout (debug)

Falls back to console-only if no endpoint is set, so dev runs still work.
"""
from __future__ import annotations
import logging
import os
import threading
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

log = logging.getLogger(__name__)

_lock = threading.Lock()
_provider: Optional[TracerProvider] = None


def get_tracer(service_name: Optional[str] = None) -> trace.Tracer:
    global _provider
    with _lock:
        if _provider is None:
            _provider = _build_provider(service_name)
            trace.set_tracer_provider(_provider)
    return trace.get_tracer("st_telemetry")


def force_flush(timeout_ms: int = 5000) -> None:
    """Block until queued spans are exported. Critical before container exit."""
    with _lock:
        if _provider is not None:
            try:
                _provider.force_flush(timeout_ms)
            except Exception as e:
                log.debug("force_flush failed: %s", e)


def _build_provider(service_name: Optional[str]) -> TracerProvider:
    name = (
        os.environ.get("OTEL_SERVICE_NAME")
        or service_name
        or os.environ.get("MODAL_APP_NAME")
        or "modal-workload"
    )
    resource = Resource.create({
        "service.name": name,
        "telemetry.sdk.language": "python",
        "modal.user": os.environ.get("MODAL_USER", "unknown"),
        "modal.task_id": os.environ.get("MODAL_TASK_ID", ""),
    })
    provider = TracerProvider(resource=resource)

    endpoint = os.environ.get("ST_TELEMETRY_ENDPOINT")
    api_key = os.environ.get("ST_TELEMETRY_API_KEY")
    if endpoint:
        headers = {}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        traces_url = endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url, headers=headers))
        )
    if os.environ.get("ST_TELEMETRY_CONSOLE") == "1" or not endpoint:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    return provider
