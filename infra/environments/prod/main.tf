locals {
  common_tags = {
    CostCenter  = "personal"
    Environment = var.environment
    ManagedBy   = "terraform"
    Project     = var.project_name
    Repository  = var.github_repository
  }

  repository_names = {
    api        = "${var.project_name}-${var.environment}-api"
    operations = "${var.project_name}-${var.environment}-operations"
  }
}

module "ecr" {
  source = "../../modules/ecr"

  repository_names       = local.repository_names
  release_images_to_keep = var.ecr_release_images_to_keep
  tags                   = local.common_tags
}

module "runtime_containers" {
  source = "../../modules/runtime-containers"

  name_prefix = "${var.project_name}/${var.environment}"
  tags        = local.common_tags
}

module "frontend" {
  source = "../../modules/frontend"

  name_prefix          = "${var.project_name}-${var.environment}"
  aws_account_id       = var.aws_account_id
  github_repository    = var.frontend_github_repository
  github_owner_id      = var.frontend_github_owner_id
  github_repository_id = var.frontend_github_repository_id
  github_environment   = var.github_environment
  tags                 = local.common_tags
}

module "cognito" {
  source = "../../modules/cognito"

  name_prefix   = "${var.project_name}-${var.environment}"
  aws_region    = var.aws_region
  domain_prefix = var.cognito_domain_prefix
  web_hostname  = module.frontend.distribution_domain_name
  tags          = local.common_tags
}

module "api" {
  source = "../../modules/api"

  name_prefix            = "${var.project_name}-${var.environment}"
  image_repository_url   = module.ecr.repository_urls["api"]
  image_digest           = var.api_image_digest
  runtime_container_arn  = module.runtime_containers.container_arns["api"]
  web_origin             = module.frontend.web_origin
  cognito_issuer         = module.cognito.issuer
  cognito_client_id      = module.cognito.client_id
  cognito_required_scope = module.cognito.required_scope
  brapi_daily_limit      = var.brapi_daily_limit
  reserved_concurrency   = var.lambda_reserved_concurrency
  memory_size            = var.lambda_memory_size
  timeout_seconds        = var.lambda_timeout_seconds
  log_retention_days     = var.log_retention_days
  tags                   = local.common_tags
}

module "operations" {
  source = "../../modules/operations"

  name_prefix           = "${var.project_name}-${var.environment}"
  image_repository_url  = module.ecr.repository_urls["operations"]
  image_repository_arn  = module.ecr.repository_arns["operations"]
  image_digest          = var.operations_image_digest
  runtime_container_arn = module.runtime_containers.container_arns["operations"]
  aws_region            = var.aws_region
  brapi_daily_limit     = var.brapi_daily_limit
  cpu                   = var.operations_cpu
  memory                = var.operations_memory
  log_retention_days    = var.log_retention_days
  smtp_host             = var.smtp_host
  smtp_port             = var.smtp_port
  smtp_user             = var.smtp_user
  smtp_from             = var.smtp_from
  smtp_to               = var.notification_email
  tags                  = local.common_tags
}

module "scheduling" {
  source = "../../modules/scheduling"

  name_prefix           = "${var.project_name}-${var.environment}"
  cluster_arn           = module.operations.cluster_arn
  task_definition_arn   = module.operations.task_definition_arn
  task_role_arn         = module.operations.task_role_arn
  execution_role_arn    = module.operations.execution_role_arn
  network_configuration = module.operations.public_network_configuration
  timezone              = var.scheduler_timezone
  enabled               = var.schedules_enabled
  intraday_expression   = var.intraday_schedule_expression
  daily_expression      = var.daily_schedule_expression
  alert_expression      = var.alert_schedule_expression
  log_retention_days    = var.log_retention_days
  tags                  = local.common_tags
}

module "observability" {
  source = "../../modules/observability"

  name_prefix               = "${var.project_name}-${var.environment}"
  environment               = var.environment
  api_id                    = module.api.http_api_id
  api_stage_name            = module.api.stage_name
  task_state_log_group_name = module.scheduling.task_state_log_group_name
  scheduler_group_name      = module.scheduling.schedule_group_name
  notification_email        = var.notification_email
  monthly_budget_usd        = var.monthly_budget_usd
  tags                      = local.common_tags
}

check "production_identity" {
  assert {
    condition     = var.aws_account_id == "351093152305"
    error_message = "Production must target AWS account 351093152305."
  }

  assert {
    condition     = var.github_repository == "Guilherme-Gotardo/opcoes-ia"
    error_message = "Production OIDC is restricted to Guilherme-Gotardo/opcoes-ia."
  }
}

check "production_frontend" {
  assert {
    condition     = var.frontend_github_repository == "Guilherme-Gotardo/opcoes-ia-web"
    error_message = "The production frontend publisher must be restricted to Guilherme-Gotardo/opcoes-ia-web."
  }
}
