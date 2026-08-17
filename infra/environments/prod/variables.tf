variable "project_name" {
  description = "Stable project identifier used in names and tags."
  type        = string
  default     = "opcoes-ia"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "project_name must contain only lowercase letters, digits, and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "prod"

  validation {
    condition     = var.environment == "prod"
    error_message = "This composition is restricted to prod."
  }
}

variable "aws_account_id" {
  description = "AWS account that owns production."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "AWS production region."
  type        = string

  validation {
    condition     = var.aws_region == "sa-east-1"
    error_message = "Production is restricted to sa-east-1."
  }
}

variable "github_repository" {
  description = "Source repository used in tags and OIDC bootstrap."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/name form."
  }
}

variable "github_environment" {
  description = "Protected GitHub environment for production release jobs."
  type        = string

  validation {
    condition     = length(trimspace(var.github_environment)) > 0
    error_message = "github_environment cannot be empty."
  }
}

variable "frontend_github_repository" {
  description = "Frontend repository trusted by the static bundle publish role."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.frontend_github_repository))
    error_message = "frontend_github_repository must use owner/name form."
  }
}

variable "frontend_github_owner_id" {
  description = "Immutable GitHub owner ID used by the frontend OIDC subject."
  type        = string
}

variable "frontend_github_repository_id" {
  description = "Immutable frontend repository ID used by the OIDC subject."
  type        = string
}

variable "cognito_domain_prefix" {
  description = "Unique prefix for the AWS-managed Cognito login domain."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.cognito_domain_prefix))
    error_message = "cognito_domain_prefix must be 1-63 lowercase letters, digits, or internal hyphens."
  }
}

variable "notification_email" {
  description = "Address reserved for later SNS and Budget subscriptions."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "notification_email must be a valid email address."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly AWS alert threshold reserved for the observability module."
  type        = number

  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 100
    error_message = "monthly_budget_usd must be greater than zero and no more than 100."
  }
}

variable "ecr_release_images_to_keep" {
  description = "Recent immutable releases retained in each ECR repository."
  type        = number
  default     = 10

  validation {
    condition     = var.ecr_release_images_to_keep >= 5 && floor(var.ecr_release_images_to_keep) == var.ecr_release_images_to_keep
    error_message = "Keep at least five whole releases for rollback."
  }
}

variable "api_image_digest" {
  description = "Immutable API image digest supplied by the approved release."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "api_image_digest must be a sha256 digest."
  }
}

variable "operations_image_digest" {
  description = "Immutable operations image digest supplied by the approved release."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.operations_image_digest))
    error_message = "operations_image_digest must be a sha256 digest."
  }
}

variable "lambda_reserved_concurrency" {
  description = "Reserved API concurrency constrained for the Neon pool; -1 is allowed only for disabled-schedule smoke before AWS raises a new-account quota."
  type        = number
  default     = 20

  validation {
    condition     = contains([-1, 20], var.lambda_reserved_concurrency)
    error_message = "Production Lambda concurrency must be 20, or -1 temporarily while schedules remain disabled and the account quota blocks reservations."
  }
}

variable "lambda_memory_size" {
  description = "API Lambda memory in MiB."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "API Lambda timeout in seconds."
  type        = number
  default     = 30
}

variable "operations_cpu" {
  description = "Fargate CPU units for each ephemeral operations task."
  type        = number
  default     = 512
}

variable "operations_memory" {
  description = "Fargate memory in MiB for each ephemeral operations task."
  type        = number
  default     = 1024
}

variable "brapi_daily_limit" {
  description = "Shared nonsecret Brapi daily request budget."
  type        = number
  default     = 600
}

variable "log_retention_days" {
  description = "Finite retention for the runtime log groups."
  type        = number
  default     = 30
}

variable "scheduler_timezone" {
  description = "IANA timezone interpreted directly by EventBridge Scheduler."
  type        = string
  default     = "America/Sao_Paulo"

  validation {
    condition     = var.scheduler_timezone == "America/Sao_Paulo"
    error_message = "Production schedules must use America/Sao_Paulo."
  }
}

variable "schedules_enabled" {
  description = "Cutover gate; false until every legacy scheduler is disabled."
  type        = bool
  default     = false
}

variable "intraday_schedule_expression" {
  description = "Fourteen half-hour triggers from 10:00 through 16:30."
  type        = string
  default     = "cron(0/30 10-16 ? * MON-FRI *)"
}

variable "daily_schedule_expression" {
  description = "Daily pipeline trigger after market close."
  type        = string
  default     = "cron(10 17 ? * MON-FRI *)"
}

variable "alert_schedule_expression" {
  description = "Independent missing-pipeline alert trigger."
  type        = string
  default     = "cron(30 18 ? * MON-FRI *)"
}

variable "smtp_host" {
  description = "Optional nonsecret SMTP hostname for operations."
  type        = string
  default     = ""
}

variable "smtp_port" {
  description = "Optional nonsecret SMTP STARTTLS port."
  type        = number
  default     = 587
}

variable "smtp_user" {
  description = "Optional nonsecret SMTP username."
  type        = string
  default     = ""
}

# The sending identity is created and verified before the channel is switched
# on, so this address is populated one apply earlier than smtp_host.
variable "smtp_from" {
  description = "Nonsecret address verified for sending; also the SMTP sender."
  type        = string
}

# Deliberately not derived from notification_email. That address is the SNS
# recipient for budget and alarms; reusing it here published a recipient
# without a host and turned "channel not configured" into a hard failure.
variable "smtp_to" {
  description = "Optional nonsecret recipient of report and alert email."
  type        = string
  default     = ""
}
