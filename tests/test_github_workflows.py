from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> tuple[str, dict]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return text, yaml.load(text, Loader=yaml.BaseLoader)


def test_ci_uses_disposable_postgres_full_suite_openspec_and_images():
    text, workflow = _workflow("ci.yml")
    assert "postgres:16-alpine" in text
    assert "localhost:5433/opcoes_ia" in text
    assert "secrets.DATABASE_URL" not in text
    assert "pytest -q" in text
    assert "openspec validate --all --strict" in text
    assert "Dockerfile.api" in text and "Dockerfile.operations" in text
    assert "checkov-action" in text and text.count("trivy-action") == 2
    assert "schedule" not in workflow["on"]


def test_terraform_plan_uses_read_role_and_publishes_reviewable_text():
    text, workflow = _workflow("terraform-plan.yml")
    assert "opcoes-ia-prod-github-plan" in text
    assert "id-token: write" in text
    assert "terraform-plan-${{ github.event.pull_request.number }}" in text
    assert "tfplan.txt" in text
    assert "terraform apply" not in text
    assert "secrets." not in text
    assert "schedule" not in workflow["on"]


def test_release_serializes_tests_scans_migration_and_digest_deploy():
    text, workflow = _workflow("release.yml")
    assert workflow["concurrency"]["group"] == "release-prod"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert "environment: Principal" in text
    for role in ("publish", "migration", "deploy"):
        assert f"opcoes-ia-prod-github-{role}" in text
    assert "Partial immutable release exists; refusing rebuild." in text
    assert "image-scan-complete" in text
    assert "python -m src.db.bootstrap" in text
    assert "needs: [publish, migrate]" in text
    assert "needs.publish.outputs.api_digest" in text
    assert "needs.publish.outputs.operations_digest" in text
    assert "list-secret-version-ids" in text
    assert "has no AWSCURRENT version" in text
    assert "openapi-${GITHUB_SHA}.json" in text
    assert "schedule" not in workflow["on"]


def test_no_operational_github_cron_or_cloudflare_credential_remains():
    assert not (WORKFLOWS / "daily-etl.yml").exists()
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in WORKFLOWS.glob("*.yml")
    )
    assert "CLOUDFLARE" not in combined.upper()
    assert "cron:" not in combined
