variable "name_prefix" {
  description = "Prefix used by operational resources."
  type        = string
}

variable "image_repository_url" {
  description = "ECR repository URL for the operations runtime."
  type        = string
}

variable "image_digest" {
  description = "Immutable sha256 digest promoted by the release workflow."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be an immutable sha256 digest."
  }
}

variable "image_repository_arn" {
  description = "Exact ECR repository from which ECS may pull layers."
  type        = string
}

variable "runtime_container_arn" {
  description = "Secrets Manager JSON container injected by key into ECS."
  type        = string
}

variable "aws_region" {
  description = "Region used by the awslogs driver."
  type        = string
}

variable "brapi_daily_limit" {
  description = "Nonsecret daily provider budget."
  type        = number
  default     = 600
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "Finite CloudWatch retention for operations logs."
  type        = number
  default     = 30
}

variable "vpc_cidr" {
  description = "Small public VPC CIDR dedicated to ephemeral tasks."
  type        = string
  default     = "10.42.0.0/24"
}

variable "smtp_host" {
  description = "Optional nonsecret SMTP hostname."
  type        = string
  default     = ""
}

variable "smtp_port" {
  description = "Optional nonsecret SMTP port."
  type        = number
  default     = 587
}

variable "smtp_user" {
  description = "Optional nonsecret SMTP username."
  type        = string
  default     = ""
}

variable "smtp_from" {
  description = "Optional nonsecret SMTP sender."
  type        = string
  default     = ""
}

variable "smtp_to" {
  description = "Optional nonsecret SMTP recipient."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
