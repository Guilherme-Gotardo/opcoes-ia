# Terraform infrastructure

The production account is `351093152305`, the AWS region is `sa-east-1`, the
Terraform environment is `prod`, and privileged release jobs use the protected
GitHub environment `Principal`. Runtime secrets are never Terraform inputs. The
checked `prod.auto.tfvars` contains only the nonsecret AWS/Cognito inventory also
recorded in `docs/RUNBOOK-CLOUD.md`.

## One-time bootstrap

The bootstrap starts with Terraform's implicit local state because its first job
is to create the remote backend and GitHub OIDC identities. In a completely
empty account, temporarily remove `backend "s3" {}` from
`infra/bootstrap/versions.tf`; Terraform cannot initialize that backend before
this root module creates its bucket. This is the only bootstrap transition that
changes the backend declaration. Renew local AWS authentication first, verify
the account, and then run:

```bash
aws sts get-caller-identity --query Account --output text
terraform -chdir=infra/bootstrap init -reconfigure
terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=infra/bootstrap apply bootstrap.tfplan
```

The identity must print exactly `351093152305`. The apply creates:

- `opcoes-ia-terraform-state-351093152305`, with AES256 default encryption,
  versioning, ownership enforcement, public access blocked, TLS-only access,
  and destruction protection;
- the GitHub Actions OIDC provider, with no permanent AWS access key;
- separate plan, image publish, migration, and deploy roles.

Configure the GitHub environment `Principal` before using privileged roles. It
must require approval and allow deployments only from `main`. AWS sees an
environment-based OIDC subject instead of a branch subject, so that GitHub
deployment-branch rule is the branch restriction for publish, migration, and
deploy. The plan role separately trusts only the exact repository pull-request
subject.

## Move bootstrap state to S3

Keep the local state backup until the migrated state has been inspected. After
the first apply, restore `backend "s3" {}` in the existing `terraform` block in
`infra/bootstrap/versions.tf`. This is an explicit one-time repository
transition: do not initialize it before the bucket exists, and do not leave
bootstrap on local state after the migration. Then move the state with:

```bash
terraform -chdir=infra/bootstrap init \
  -migrate-state \
  -force-copy \
  -backend-config=backend.hcl
terraform -chdir=infra/bootstrap state list
```

Both bootstrap and production backends use Terraform's native S3 lock file
(`use_lockfile = true`); there is no DynamoDB lock table. S3 versioning is the
recovery path for accidental state changes.

Initialize production only after bootstrap and state migration succeed:

```bash
terraform -chdir=infra/environments/prod init -backend-config=backend.hcl
terraform -chdir=infra/environments/prod plan
```

Do not apply production from an unreviewed local plan. The future release
workflow assumes the dedicated deploy role and applies a reviewed plan.

## Role scopes

| Role suffix | Trusted GitHub subject | AWS scope |
|---|---|---|
| `plan` | `repo:Guilherme-Gotardo/opcoes-ia:pull_request` | Read production state and metadata for managed AWS resources; create only the state lock object |
| `publish` | `repo:Guilherme-Gotardo/opcoes-ia:environment:Principal` | Authenticate to ECR and push/inspect images in the two project repositories |
| `migration` | `repo:Guilherme-Gotardo/opcoes-ia:environment:Principal` | No AWS data-plane permission; the protected job receives the direct Neon URL |
| `deploy` | `repo:Guilherme-Gotardo/opcoes-ia:environment:Principal` | Read/write production state and manage the explicit API, Cognito, ECR, ECS, IAM, logs, network and secret-container control planes |

The deploy policy intentionally covers only resources implemented so far. Add
explicit resource-scoped actions as later modules are introduced; do not replace
them with administrator access. APIs that cannot authorize creation/discovery
against a not-yet-known ARN use exact actions with `Resource = "*"`; every such
action is reviewed in the allowlist of `scripts/check_terraform.py`.

## Offline checks

These checks require provider downloads but no cloud credentials:

```bash
terraform fmt -check -recursive infra
terraform -chdir=infra/bootstrap init -backend=false
terraform -chdir=infra/bootstrap validate
terraform -chdir=infra/environments/prod init -backend=false
terraform -chdir=infra/environments/prod validate
python scripts/check_terraform.py
pytest -q tests/test_terraform_infrastructure.py
```

Cognito and the regional `execute-api` endpoint are declared without custom DNS
or external infrastructure provider. EventBridge schedules are still absent, so
nothing in this stage can trigger an operational pipeline.
