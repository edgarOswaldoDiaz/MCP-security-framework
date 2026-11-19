"""Explicit OpenTelemetry SDK initialization for agent services."""
from __future__ import annotations

import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("agentops.telemetry")


def _resource_attributes() -> dict[str, str]:
    attributes: dict[str, str] = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "agentops-service"),
    }
    raw = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "")
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() and value.strip():
            attributes[key.strip()] = value.strip()
    return attributes


def configure_telemetry() -> None:
    """Set a batch OTLP exporter; safe to call once during process startup."""
    # OpenTelemetry API may already have exposed a proxy provider; a concrete
    # provider should be installed before the app/server starts creating spans.
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=endpoint.startswith("http://"),
    )
    resource = Resource.create(_resource_attributes())
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    metric_exporter = OTLPMetricExporter(
        endpoint=endpoint,
        insecure=endpoint.startswith("http://"),
    )
    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
    logger.info("OpenTelemetry traces and metrics configured", extra={"otlp_endpoint": endpoint})
