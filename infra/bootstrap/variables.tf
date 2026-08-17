variable "aws_account_id" {
  description = "AWS account that owns the production infrastructure."
  type        = string
  default     = "351093152305"

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "AWS region used by the project."
  type        = string
  default     = "sa-east-1"

  validation {
    condition     = contains(["sa-east-1"], var.aws_region)
    error_message = "This production bootstrap is restricted to sa-east-1."
  }
}

variable "github_repository" {
  description = "GitHub repository in owner/name form."
  type        = string
  default     = "Guilherme-Gotardo/opcoes-ia"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/name form."
  }
}

variable "github_environment" {
  description = "Protected GitHub environment used by production release jobs."
  type        = string
  default     = "Principal"

  validation {
    condition     = length(trimspace(var.github_environment)) > 0
    error_message = "github_environment cannot be empty."
  }
}

variable "project_name" {
  description = "Stable project identifier used in resource names and tags."
  type        = string
  default     = "opcoes-ia"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "project_name must contain only lowercase letters, digits, and hyphens."
  }
}
