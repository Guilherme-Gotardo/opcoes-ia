variable "name_prefix" {
  description = "Prefix used by API resources."
  type        = string
}

variable "image_repository_url" {
  description = "ECR repository URL for the API runtime."
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

variable "runtime_container_arn" {
  description = "Secrets Manager container read by the Lambda bootstrap."
  type        = string
}

variable "web_origin" {
  description = "Exact HTTPS browser origin accepted by FastAPI CORS."
  type        = string
}

variable "cognito_issuer" {
  description = "Exact Cognito User Pool issuer."
  type        = string
}

variable "cognito_client_id" {
  description = "Public Cognito app client accepted by the API."
  type        = string
}

variable "cognito_required_scope" {
  description = "OAuth scope required by gateway and FastAPI."
  type        = string
}

variable "brapi_daily_limit" {
  description = "Nonsecret daily request budget exposed to the API runtime."
  type        = number
  default     = 600
}

variable "reserved_concurrency" {
  description = "Maximum simultaneous Lambda executions."
  type        = number
  default     = 2
}

variable "memory_size" {
  description = "Lambda memory in MiB."
  type        = number
  default     = 512
}

variable "timeout_seconds" {
  description = "Lambda request timeout in seconds."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "Finite CloudWatch retention for API logs."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
