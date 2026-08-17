import json

import pytest

from src.observability import metrics


def _line(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_execution_emf_has_finite_dimensions_and_duration(monkeypatch, capsys):
    monkeypatch.setenv("OPCOES_IA_ENV", "test")
    metrics.emit_execution(flow="daily", status="parcial", duration_ms=12.5)
    event = _line(capsys)

    assert event["environment"] == "test"
    assert event["component"] == "operations"
    assert event["flow"] == "daily"
    assert event["status"] == "parcial"
    assert event["ExecutionCount"] == 1
    assert event["ExecutionDurationMs"] == 12.5
    definition = event["_aws"]["CloudWatchMetrics"][0]
    assert definition["Namespace"] == "OpcoesIA"
    assert "execution_id" not in definition["Dimensions"][0]


@pytest.mark.parametrize("status", ["sucesso", "parcial", "falha", "bloqueado"])
def test_source_emf_preserves_operational_state(status, capsys):
    metrics.emit_source(
        source="brapi", status=status, attempted=3, persisted=2, failed=1,
    )
    event = _line(capsys)
    assert event["source"] == "brapi"
    assert event["status"] == status
    assert event["SourceTargetsAttempted"] == 3
    assert event["SourceRecordsPersisted"] == 2
    assert event["SourceTargetsFailed"] == 1


def test_neon_error_identifies_component_without_dsn(monkeypatch, capsys):
    monkeypatch.setenv("OPCOES_IA_COMPONENT", "api")
    metrics.emit_neon_connection_error()
    event = _line(capsys)
    assert event["component"] == "api"
    assert event["dependency"] == "neon"
    assert event["NeonConnectionError"] == 1
    assert "database_url" not in event


def test_operational_alert_uses_finite_condition(capsys):
    metrics.emit_operational_alert("orfa")
    event = _line(capsys)
    assert event["flow"] == "daily"
    assert event["condition"] == "orfa"
    assert event["OperationalAlertCount"] == 1
