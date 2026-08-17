"""CloudWatch Embedded Metric Format sem SDK nem chamada de rede adicional."""
from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping


NAMESPACE = "OpcoesIA"


def _environment() -> str:
    return os.getenv("OPCOES_IA_ENV", "local")


def emit_metric(
    *,
    component: str,
    dimensions: Mapping[str, str],
    values: Mapping[str, tuple[float, str]],
) -> None:
    """Escreve uma linha EMF; nomes e dimensões são definidos pelo chamador."""
    if not values:
        raise ValueError("EMF exige ao menos uma métrica")
    dims = {
        "environment": _environment(),
        "component": component,
        **{str(key): str(value) for key, value in dimensions.items()},
    }
    metrics = [
        {"Name": name, "Unit": unit}
        for name, (_, unit) in values.items()
    ]
    event = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [list(dims)],
                "Metrics": metrics,
            }],
        },
        **dims,
        **{name: value for name, (value, _) in values.items()},
    }
    print(json.dumps(event, separators=(",", ":")), file=sys.stdout, flush=True)


def emit_execution(*, flow: str, status: str, duration_ms: float) -> None:
    emit_metric(
        component="operations",
        dimensions={"flow": flow, "status": status},
        values={
            "ExecutionCount": (1, "Count"),
            "ExecutionDurationMs": (duration_ms, "Milliseconds"),
        },
    )


def emit_stage(*, flow: str, stage: str, status: str, duration_ms: float) -> None:
    emit_metric(
        component="operations",
        dimensions={"flow": flow, "stage": stage, "status": status},
        values={
            "StageCount": (1, "Count"),
            "StageDurationMs": (duration_ms, "Milliseconds"),
        },
    )


def emit_source(
    *, source: str, status: str, attempted: int, persisted: int, failed: int,
) -> None:
    emit_metric(
        component="operations",
        dimensions={"source": source, "status": status},
        values={
            "SourceCount": (1, "Count"),
            "SourceTargetsAttempted": (attempted, "Count"),
            "SourceRecordsPersisted": (persisted, "Count"),
            "SourceTargetsFailed": (failed, "Count"),
        },
    )


def emit_neon_connection_error() -> None:
    emit_metric(
        component=os.getenv("OPCOES_IA_COMPONENT", "database"),
        dimensions={"dependency": "neon", "status": "falha"},
        values={"NeonConnectionError": (1, "Count")},
    )


def emit_operational_alert(condition: str) -> None:
    emit_metric(
        component="operations",
        dimensions={"flow": "daily", "condition": condition},
        values={"OperationalAlertCount": (1, "Count")},
    )
