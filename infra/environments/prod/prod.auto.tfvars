# Production nonsecret inventory. Credentials and provider tokens are injected
# through the GitHub environment or AWS Secrets Manager, never through tfvars.
aws_account_id                = "351093152305"
aws_region                    = "sa-east-1"
github_repository             = "Guilherme-Gotardo/opcoes-ia"
github_environment            = "Principal"
frontend_github_repository    = "Guilherme-Gotardo/opcoes-ia-web"
frontend_github_owner_id      = "179357365"
frontend_github_repository_id = "1335621735"
cognito_domain_prefix         = "opcoes-ia-prod"
notification_email            = "guilher.gotardo@gmail.com"
monthly_budget_usd            = 5

ecr_release_images_to_keep = 10

# Email channel. None of these is a secret: smtp_user is the access key ID, the
# public half of the credential, like a username. Only SMTP_PASSWORD lives in
# Secrets Manager. Host and recipient must be set together or both left empty —
# a precondition on the task definition refuses the apply otherwise.
smtp_from = "guilher.gotardo@gmail.com"
smtp_host = "email-smtp.sa-east-1.amazonaws.com"
smtp_port = 587
smtp_user = "AKIAVDPWILIY72V5FZ7R"
smtp_to   = "guilher.gotardo@gmail.com"

scheduler_timezone           = "America/Sao_Paulo"
schedules_enabled            = true
intraday_schedule_expression = "cron(0/30 10-16 ? * MON-FRI *)"
daily_schedule_expression    = "cron(10 17 ? * MON-FRI *)"
alert_schedule_expression    = "cron(30 18 ? * MON-FRI *)"

# Supplied by the approved release workflow with -var; no mutable image tag is
# accepted. They are intentionally not persisted in this inventory file.
