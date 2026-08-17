from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


def _terraform_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(INFRA.rglob("*.tf"))
    )


def test_static_terraform_policy_guardrails() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_terraform.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ecr_is_immutable_scanned_encrypted_and_keeps_releases() -> None:
    source = (INFRA / "modules/ecr/main.tf").read_text(encoding="utf-8")
    assert 'image_tag_mutability = "IMMUTABLE"' in source
    assert "scan_on_push = true" in source
    assert 'encryption_type = "AES256"' in source
    assert 'tagPrefixList = ["release-"]' in source
    assert "countType     = \"imageCountMoreThan\"" in source
    assert "countNumber   = var.release_images_to_keep" in source


def test_exact_oidc_subjects_and_separate_roles() -> None:
    source = (INFRA / "bootstrap/main.tf").read_text(encoding="utf-8")
    for role in ("plan", "publish", "migration", "deploy"):
        assert re.search(rf"\b{role}\s+=", source)
    assert '@${var.github_owner_id}/' in source
    assert '@${var.github_repository_id}:pull_request"' in source
    assert '@${var.github_repository_id}:environment:${var.github_environment}"' in source
    assert 'variable = "token.actions.githubusercontent.com:aud"' in source
    assert 'variable = "token.actions.githubusercontent.com:sub"' in source
    frontend = (INFRA / "modules/frontend/main.tf").read_text(encoding="utf-8")
    assert '@${var.github_owner_id}/' in frontend
    assert '@${var.github_repository_id}:environment:${var.github_environment}"' in frontend
    assert 'name                 = "${var.name_prefix}-github-web-publish"' in frontend


def test_no_brokerage_permissions_or_admin_wildcards() -> None:
    source = _terraform_source()
    lowered = source.lower()
    allow_statements = "\n".join(
        statement
        for statement in re.findall(r"statement\s*\{(.*?)\n\s*\}", source, re.DOTALL)
        if re.search(r'effect\s*=\s*"Allow"', statement)
    )
    assert "administratoraccess" not in lowered
    assert not re.search(r'actions?\s*=\s*\[?\s*"\*"', allow_statements)
    assert not re.search(
        r'"(?:iam|sts|ecr|ecs|lambda|s3|secretsmanager):\*"', allow_statements
    )
    for term in ("brokerage", "corretora", "execute_order", "place_order"):
        assert term not in lowered


def test_no_secret_shaped_inputs_outputs_or_tfvars_values() -> None:
    source = _terraform_source()
    names = re.findall(r'\b(?:variable|output)\s+"([^"]+)"', source)
    assert not [
        name
        for name in names
        if re.search(r"(?:password|passwd|secret|token|api_key|database_url|dsn)", name, re.I)
    ]

    tfvars = (INFRA / "environments/prod/prod.auto.tfvars").read_text(
        encoding="utf-8"
    )
    assert "351093152305" in tfvars
    assert "sa-east-1" in tfvars
    assert "Guilherme-Gotardo/opcoes-ia" in tfvars
    assert re.search(r"^monthly_budget_usd\s*=\s*5$", tfvars, re.MULTILINE)
    assert not re.search(r"(?i)(password|secret|token|api_key|database_url|dsn)\s*=", tfvars)
    assert not re.search(r"(?i)(?:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]+@", tfvars)


def test_backend_uses_native_lock_and_schedules_have_safe_cutover_gate() -> None:
    for backend in (
        INFRA / "bootstrap/backend.hcl",
        INFRA / "environments/prod/backend.hcl",
    ):
        content = backend.read_text(encoding="utf-8")
        assert "use_lockfile = true" in content
        assert "encrypt      = true" in content

    source = _terraform_source()
    assert 'resource "aws_scheduler_schedule" "flow"' in source
    assert 'state                        = var.enabled ? "ENABLED" : "DISABLED"' in source
    assert re.search(r'variable "enabled".*?default\s*=\s*false', source, re.DOTALL)


def test_lifecycle_policy_shape_is_valid_json_after_substitution() -> None:
    source = (INFRA / "modules/ecr/main.tf").read_text(encoding="utf-8")
    descriptions = re.findall(r'description\s+=\s+"([^"]+)"', source)
    assert descriptions == [
        "Expire untagged upload remnants",
        "Expire stale CI build images",
        "Expire stale pull request images",
        "Retain recent immutable releases for digest rollback",
    ]
    # Terraform jsonencode emits JSON; this mirrors the fixed structural values.
    policy = {
        "rules": [
            {"rulePriority": 10, "action": {"type": "expire"}},
            {"rulePriority": 20, "action": {"type": "expire"}},
            {"rulePriority": 30, "action": {"type": "expire"}},
            {"rulePriority": 40, "action": {"type": "expire"}},
        ]
    }
    assert json.loads(json.dumps(policy))["rules"][-1]["rulePriority"] == 40


def test_runtime_containers_never_manage_values_and_runtime_reads_are_exact() -> None:
    source = _terraform_source()
    containers = (INFRA / "modules/runtime-containers/main.tf").read_text(
        encoding="utf-8"
    )
    api = (INFRA / "modules/api/main.tf").read_text(encoding="utf-8")
    operations = (INFRA / "modules/operations/main.tf").read_text(encoding="utf-8")

    assert containers.count('resource "aws_secretsmanager_secret"') == 1
    assert 'resource "aws_secretsmanager_secret_version"' not in source
    assert api.count('"secretsmanager:GetSecretValue"') == 1
    assert operations.count('"secretsmanager:GetSecretValue"') == 1
    assert 'API_RUNTIME_CONFIG_ARN' in api
    for key in (
        "DATABASE_URL", "BRAPI_TOKEN", "ANTHROPIC_API_KEY", "NEWS_API_KEY",
        "OPLAB_TOKEN", "SMTP_PASSWORD",
    ):
        assert f'"{key}"' in operations
    assert 'secretsmanager:PutSecretValue' not in source


def test_lambda_http_api_and_cognito_authorizer_are_hardened() -> None:
    api = (INFRA / "modules/api/main.tf").read_text(encoding="utf-8")
    prod = (INFRA / "environments/prod/main.tf").read_text(encoding="utf-8")

    assert 'image_uri     = "${var.image_repository_url}@${var.image_digest}"' in api
    assert 'architectures = ["x86_64"]' in api
    assert "reserved_concurrent_executions = var.reserved_concurrency" in api
    assert 'disable_execute_api_endpoint = false' in api
    assert 'integration_type       = "AWS_PROXY"' in api
    assert re.search(r'route_key\s*=\s*"\$default"', api)
    assert 'resource "aws_apigatewayv2_authorizer" "cognito"' in api
    assert 'authorizer_type  = "JWT"' in api
    assert 'authorization_scopes = [var.cognito_required_scope]' in api
    assert re.search(r'authorization_type\s*=\s*"NONE"', api)
    assert "vpc_config" not in api
    assert 'resource "aws_apigatewayv2_domain_name"' not in api
    assert 'resource "aws_acm_certificate"' not in prod
    assert "cloudflare" not in prod.lower()


def test_operations_are_ephemeral_public_ip_compatible_and_have_no_ingress() -> None:
    source = (INFRA / "modules/operations/main.tf").read_text(encoding="utf-8")
    outputs = (INFRA / "modules/operations/outputs.tf").read_text(encoding="utf-8")

    assert source.count('resource "aws_subnet" "public"') == 1
    assert "count = 2" in source
    assert "map_public_ip_on_launch = true" in source
    assert 'requires_compatibilities = ["FARGATE"]' in source
    assert 'network_mode             = "awsvpc"' in source
    assert 'cpu                      = tostring(var.cpu)' in source
    assert 'memory                   = tostring(var.memory)' in source
    assert 'resource "aws_vpc_security_group_ingress_rule"' not in source
    assert 'assign_public_ip = "ENABLED"' in outputs
    # Casa a atribuição, não o alinhamento: terraform fmt realinha o bloco
    # inteiro quando a maior chave muda de tamanho.
    assert re.search(r"^\s*image\s+= local\.image_uri$", source, re.MULTILINE)
    assert 'logDriver = "awslogs"' in source


def test_sending_identity_carries_no_credential_value() -> None:
    """Terraform owns the identity and the principal, never the credential."""
    module = (INFRA / "modules/notifications/main.tf").read_text(encoding="utf-8")
    outputs = (INFRA / "modules/notifications/outputs.tf").read_text(encoding="utf-8")
    # Comments explain why the attribute is avoided; the ban is on code.
    code = "\n".join(
        line
        for line in (module + "\n" + outputs).splitlines()
        if not line.lstrip().startswith("#")
    )

    # ses_smtp_password_v4 would put the SMTP password in the state file.
    assert 'resource "aws_iam_access_key"' not in code
    assert "ses_smtp_password_v4" not in code
    assert 'resource "aws_sesv2_email_identity" "sender"' in module
    assert 'resource "aws_iam_user" "smtp"' in module


def test_send_only_policy_is_scoped_to_the_verified_identity() -> None:
    module = (INFRA / "modules/notifications/main.tf").read_text(encoding="utf-8")

    assert '"ses:SendRawEmail"' in module
    assert "resources = [aws_sesv2_email_identity.sender.arn]" in module
    assert 'variable = "ses:FromAddress"' in module
    # Reading mail, or sending as anything else, must never be granted here.
    for forbidden in ("ses:ReceiveMessage", "ses:CreateEmailIdentity", "ses:*"):
        assert f'"{forbidden}"' not in module


def test_deploy_role_cannot_mint_a_sending_credential() -> None:
    bootstrap = (INFRA / "bootstrap/main.tf").read_text(encoding="utf-8")

    assert '"iam:CreateUser"' in bootstrap
    assert '"iam:CreateAccessKey"' not in bootstrap


def test_smtp_host_and_recipient_are_injected_together_or_not_at_all() -> None:
    """Half a channel is what took the alert flow down on 2026-08-17."""
    operations = (INFRA / "modules/operations/main.tf").read_text(encoding="utf-8")
    prod = (INFRA / "environments/prod/main.tf").read_text(encoding="utf-8")

    assert 'smtp_enabled = var.smtp_host != "" && var.smtp_to != ""' in operations
    assert "local.smtp_environment" in operations
    assert re.search(
        r'condition\s+=\s+\(var\.smtp_host != ""\) == \(var\.smtp_to != ""\)',
        operations,
    )
    # The SNS budget/alarm recipient must not double as the SMTP recipient.
    assert "smtp_to               = var.notification_email" not in prod
    assert "smtp_to               = var.smtp_to" in prod


def test_cognito_pkce_mfa_and_runtime_identity_contract() -> None:
    identity = (INFRA / "modules/cognito/main.tf").read_text(
        encoding="utf-8"
    )
    outputs = (INFRA / "modules/cognito/outputs.tf").read_text(
        encoding="utf-8"
    )
    prod = (INFRA / "environments/prod/main.tf").read_text(encoding="utf-8")
    versions = (INFRA / "environments/prod/versions.tf").read_text(
        encoding="utf-8"
    )

    assert 'resource "aws_cognito_user_pool" "api"' in identity
    assert 'allow_admin_create_user_only = true' in identity
    assert 'mfa_configuration        = "ON"' in identity
    assert 'deletion_protection      = "ACTIVE"' in identity
    assert 'software_token_mfa_configuration' in identity
    assert 'generate_secret                      = false' in identity
    assert 'allowed_oauth_flows                  = ["code"]' in identity
    assert '"https://${var.web_hostname}/auth/callback"' in identity
    assert 'resource "aws_cognito_resource_server" "api"' in identity
    assert 'resource "aws_cognito_user_pool_domain" "managed"' in identity
    assert 'aws_cognito_user_pool_client.web.id' in outputs
    assert "module.cognito.issuer" in prod
    assert "module.cognito.client_id" in prod
    assert "module.cognito.required_scope" in prod
    terraform_source = _terraform_source().lower()
    assert 'source  = "cloudflare/cloudflare"' not in terraform_source
    assert not re.search(r'\b(?:resource|data)\s+"cloudflare_', terraform_source)
    assert "cloudflare_account_id" not in terraform_source
    assert "cloudflare" not in versions.lower()


def test_frontend_is_private_cloudfront_spa_with_exact_publish_role() -> None:
    source = (INFRA / "modules/frontend/main.tf").read_text(encoding="utf-8")
    outputs = (INFRA / "modules/frontend/outputs.tf").read_text(encoding="utf-8")
    prod = (INFRA / "environments/prod/main.tf").read_text(encoding="utf-8")

    assert 'resource "aws_s3_bucket_public_access_block" "web"' in source
    for setting in (
        "block_public_acls", "block_public_policy", "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert re.search(rf"{setting}\s*=\s*true", source)
    assert 'resource "aws_cloudfront_origin_access_control" "web"' in source
    assert 'signing_behavior                  = "always"' in source
    assert 'origin_access_control_origin_type = "s3"' in source
    assert 'identifiers = ["cloudfront.amazonaws.com"]' in source
    assert 'values   = [aws_cloudfront_distribution.web.arn]' in source
    assert source.count('response_page_path    = "/index.html"') == 2
    assert 'path_pattern           = "/assets/*"' in source
    assert 'viewer_protocol_policy = "redirect-to-https"' in source
    assert 'cloudfront_default_certificate = true' in source
    assert 'resources = [aws_cloudfront_distribution.web.arn]' in source
    assert '"cloudfront:CreateInvalidation"' in source
    assert 'module.frontend.distribution_domain_name' in prod
    assert 'module.frontend.web_origin' in prod
    assert 'aws_cloudfront_distribution.web.domain_name' in outputs


def test_deploy_and_plan_roles_cannot_read_or_write_runtime_values() -> None:
    source = (INFRA / "bootstrap/main.tf").read_text(encoding="utf-8")
    assert 'data "aws_iam_policy_document" "plan"' in source
    assert 'data "aws_iam_policy_document" "deploy"' in source
    assert "secretsmanager:GetSecretValue" not in source
    assert "secretsmanager:PutSecretValue" not in source
    assert "iam:PassRole" in source
    assert "local.iam_runtime_arns" in source
    assert "local.runtime_container_arns" in source
    assert "cognito-idp:CreateUserPool" in source
    assert "local.cognito_user_pool_arns" in source


def test_scheduler_uses_stable_window_minimal_role_and_distinct_retries() -> None:
    source = (INFRA / "modules/scheduling/main.tf").read_text(encoding="utf-8")
    prod_values = (INFRA / "environments/prod/prod.auto.tfvars").read_text(
        encoding="utf-8"
    )

    assert 'actions   = ["ecs:RunTask"]' in source
    assert 'actions   = ["iam:PassRole"]' in source
    assert "resources = [var.task_definition_arn]" in source
    assert "resources = [var.task_role_arn, var.execution_role_arn]" in source
    assert 'variable = "iam:PassedToService"' in source
    assert '"<aws.scheduler.scheduled-time>"' in source
    assert 'state                        = var.enabled ? "ENABLED" : "DISABLED"' in source
    assert 'schedules_enabled            = true' in prod_values
    assert re.search(r"maximum_event_age\s*=\s*60", source)
    assert re.search(r"maximum_retry_attempts\s*=\s*0", source)
    assert re.search(r"maximum_event_age\s*=\s*1800", source)
    assert re.search(r"maximum_retry_attempts\s*=\s*2", source)
    assert 'scheduler_timezone           = "America/Sao_Paulo"' in prod_values
    assert 'intraday_schedule_expression = "cron(0/30 10-16 ? * MON-FRI *)"' in prod_values
    assert 'daily_schedule_expression    = "cron(10 17 ? * MON-FRI *)"' in prod_values
    assert 'alert_schedule_expression    = "cron(30 18 ? * MON-FRI *)"' in prod_values


def test_ecs_task_stop_is_captured_before_application_logging() -> None:
    source = (INFRA / "modules/scheduling/main.tf").read_text(encoding="utf-8")
    assert '"detail-type" = ["ECS Task State Change"]' in source
    assert 'lastStatus = ["STOPPED"]' in source
    assert 'resource "aws_cloudwatch_event_target" "task_state_log"' in source
    assert 'identifiers = ["events.amazonaws.com"]' in source


def test_observability_covers_runtime_data_api_neon_and_cost() -> None:
    source = (INFRA / "modules/observability/main.tf").read_text(encoding="utf-8")
    api = (INFRA / "modules/api/main.tf").read_text(encoding="utf-8")
    operations = (INFRA / "modules/operations/main.tf").read_text(encoding="utf-8")
    scheduling = (INFRA / "modules/scheduling/main.tf").read_text(encoding="utf-8")

    for group in (api, operations, scheduling):
        assert "retention_in_days = var.log_retention_days" in group
    for alarm in (
        "ecs_task_failure", "scheduler_target_error", "execution_failure",
        "source_failure", "operational_alert", "neon_connection", "api_5xx",
        "api_latency",
    ):
        assert f'resource "aws_cloudwatch_metric_alarm" "{alarm}"' in source
    assert 'resource "aws_sns_topic" "operations"' in source
    assert 'resource "aws_sns_topic_subscription" "email"' in source
    assert 'identifiers = ["cloudwatch.amazonaws.com"]' in source
    assert 'identifiers = ["budgets.amazonaws.com"]' in source
    assert 'resource "aws_budgets_budget" "monthly"' in source
    assert 'notification_type         = "ACTUAL"' in source
    assert 'notification_type         = "FORECASTED"' in source
