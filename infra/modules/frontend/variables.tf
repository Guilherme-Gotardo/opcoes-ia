variable "name_prefix" {
  description = "Prefix used by frontend hosting resources."
  type        = string
}

variable "aws_account_id" {
  description = "AWS account used to make the globally unique bucket name deterministic."
  type        = string
}

variable "github_repository" {
  description = "Frontend repository trusted to publish the static bundle."
  type        = string
}

variable "github_owner_id" {
  description = "Immutable GitHub owner ID embedded in the OIDC subject."
  type        = string
}

variable "github_repository_id" {
  description = "Immutable frontend repository ID embedded in the OIDC subject."
  type        = string
}

variable "github_environment" {
  description = "Protected GitHub environment used by the frontend deployment."
  type        = string
}

variable "tags" {
  description = "Tags applied to supported frontend resources."
  type        = map(string)
  default     = {}
}
