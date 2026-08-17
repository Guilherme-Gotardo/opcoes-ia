"""Credential-free Terraform policy guardrails used locally and in CI."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
TF_FILES = tuple(sorted(INFRA.rglob("*.tf")))

# AWS requires Resource="*" for these identity, discovery, authentication and
# create-before-ARN APIs. Keep this list exact; additions require review here.
UNSCOPED_ACTION_ALLOWLIST = {
    "apigateway:GET",
    "cloudfront:CreateCachePolicy",
    "cloudfront:CreateDistribution",
    "cloudfront:CreateOriginAccessControl",
    "cognito-idp:CreateUserPool",
    "cognito-idp:DescribeUserPoolDomain",
    "cognito-idp:ListUserPools",
    "cloudwatch:DescribeAlarms",
    "ec2:AssociateRouteTable",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:CreateInternetGateway",
    "ec2:CreateRoute",
    "ec2:CreateRouteTable",
    "ec2:CreateSecurityGroup",
    "ec2:CreateSubnet",
    "ec2:CreateTags",
    "ec2:CreateVpc",
    "ec2:DeleteInternetGateway",
    "ec2:DeleteRoute",
    "ec2:DeleteRouteTable",
    "ec2:DeleteSecurityGroup",
    "ec2:DeleteSubnet",
    "ec2:DeleteTags",
    "ec2:DeleteVpc",
    "ec2:DescribeAvailabilityZones",
    "ec2:DescribeInternetGateways",
    "ec2:DescribeRouteTables",
    "ec2:DescribeSecurityGroupRules",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeSubnets",
    "ec2:DescribeVpcs",
    "ec2:DetachInternetGateway",
    "ec2:DisassociateRouteTable",
    "ec2:ModifySubnetAttribute",
    "ec2:ModifyVpcAttribute",
    "ec2:RevokeSecurityGroupEgress",
    "ecr:GetAuthorizationToken",
    "ecs:CreateCluster",
    "ecs:DescribeClusters",
    "ecs:DescribeTaskDefinition",
    "ecs:ListTagsForResource",
    "ecs:RegisterTaskDefinition",
    "events:ListRules",
    "iam:GetRole",
    "iam:GetRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListRolePolicies",
    "lambda:GetFunction",
    "lambda:GetFunctionConcurrency",
    "lambda:GetPolicy",
    "lambda:ListTags",
    "logs:DescribeLogGroups",
    "logs:DescribeMetricFilters",
    "logs:DescribeResourcePolicies",
    "logs:DeleteResourcePolicy",
    "logs:ListTagsForResource",
    "logs:PutResourcePolicy",
    "scheduler:ListScheduleGroups",
    "scheduler:ListSchedules",
    "sns:GetSubscriptionAttributes",
    "sns:Unsubscribe",
    "secretsmanager:CreateSecret",
    "sts:GetCallerIdentity",
}


def _failures() -> list[str]:
    failures: list[str] = []
    combined = "\n".join(path.read_text(encoding="utf-8") for path in TF_FILES)
    lowered = combined.lower()
    allow_statements = "\n".join(
        statement
        for statement in re.findall(r"statement\s*\{(.*?)\n\s*\}", combined, re.DOTALL)
        if re.search(r'effect\s*=\s*"Allow"', statement)
    )

    forbidden_policy_patterns = {
        'wildcard IAM action': r'actions?\s*=\s*\[?\s*"\*"',
        'service-wide IAM action': r'"(?:iam|sts|ecr|ecs|lambda|s3|secretsmanager):\*"',
        'AWS managed administrator policy': r'AdministratorAccess',
    }
    for label, pattern in forbidden_policy_patterns.items():
        policy_source = combined if label == "AWS managed administrator policy" else allow_statements
        if re.search(pattern, policy_source):
            failures.append(label)

    for statement in re.findall(r"statement\s*\{(.*?)\n\s*\}", combined, re.DOTALL):
        if not re.search(r'effect\s*=\s*"Allow"', statement):
            continue
        if not re.search(r'resources\s*=\s*\[\s*"\*"\s*\]', statement):
            continue
        action_values = re.findall(
            r'actions\s*=\s*\[(.*?)\]', statement, flags=re.DOTALL
        )
        actions = {
            action
            for value in action_values
            for action in re.findall(r'"([a-z0-9]+:[A-Za-z0-9]+)"', value)
        }
        unexpected = actions - UNSCOPED_ACTION_ALLOWLIST
        if unexpected:
            failures.append(
                "unjustified unscoped IAM actions: " + ", ".join(sorted(unexpected))
            )

    for forbidden_term in ("brokerage", "corretora", "execute_order", "place_order"):
        if forbidden_term in lowered:
            failures.append(f"broker/order capability: {forbidden_term}")

    if 'resource "aws_secretsmanager_secret_version"' in combined:
        failures.append("Terraform-managed runtime credential value")

    if 'source  = "cloudflare/cloudflare"' in combined:
        failures.append("Cloudflare provider integration")
    if re.search(r'\b(?:resource|data)\s+"cloudflare_', combined):
        failures.append("Cloudflare-managed infrastructure resource")

    declaration_pattern = re.compile(r'\b(?:variable|output)\s+"([^"]+)"')
    for name in declaration_pattern.findall(combined):
        if re.search(r"(?:password|passwd|secret|token|api_key|database_url|dsn)", name, re.I):
            failures.append(f"secret-shaped Terraform variable/output: {name}")

    for tfvars in INFRA.rglob("*.tfvars"):
        content = tfvars.read_text(encoding="utf-8")
        if re.search(r"(?i)(?:password|passwd|secret|token|api_key|database_url|dsn)\s*=", content):
            failures.append(f"secret assignment in {tfvars.relative_to(ROOT)}")
        if re.search(r"(?i)(?:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]+@", content):
            failures.append(f"credentialed URL in {tfvars.relative_to(ROOT)}")

    schedule_blocks = re.findall(
        r'resource\s+"aws_scheduler_schedule"\s+"[^"]+"\s*\{(.*?)\n\}',
        combined,
        flags=re.DOTALL,
    )
    for block in schedule_blocks:
        if not re.search(r'\bstate\s*=\s*"DISABLED"', block):
            failures.append("EventBridge schedule not explicitly disabled")

    return failures


def main() -> int:
    if not TF_FILES:
        print("No Terraform files found", file=sys.stderr)
        return 1

    failures = _failures()
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    print(f"Terraform policy checks passed for {len(TF_FILES)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
