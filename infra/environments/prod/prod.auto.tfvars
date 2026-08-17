# Production nonsecret inventory. Credentials and provider tokens are injected
# through the GitHub environment or AWS Secrets Manager, never through tfvars.
aws_account_id             = "351093152305"
aws_region                 = "sa-east-1"
github_repository          = "Guilherme-Gotardo/opcoes-ia"
github_environment         = "Principal"
frontend_github_repository = "Guilherme-Gotardo/opcoes-ia-web"
cognito_domain_prefix      = "opcoes-ia-prod"
notification_email         = "guilher.gotardo@gmail.com"
monthly_budget_usd         = 5

ecr_release_images_to_keep = 10

scheduler_timezone           = "America/Sao_Paulo"
intraday_schedule_expression = "cron(0/30 10-16 ? * MON-FRI *)"
daily_schedule_expression    = "cron(10 17 ? * MON-FRI *)"
alert_schedule_expression    = "cron(30 18 ? * MON-FRI *)"

# Supplied by the approved release workflow with -var; no mutable image tag is
# accepted. They are intentionally not persisted in this inventory file.
