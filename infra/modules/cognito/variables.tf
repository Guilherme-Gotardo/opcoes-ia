variable "name_prefix" {
  description = "Prefix used by Cognito resources."
  type        = string
}

variable "aws_region" {
  description = "Region used to build the exact User Pool issuer."
  type        = string
}

variable "domain_prefix" {
  description = "Unique prefix for the Cognito managed login domain."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.domain_prefix))
    error_message = "domain_prefix must be 1-63 lowercase letters, digits, or internal hyphens."
  }
}

variable "web_hostname" {
  description = "CloudFront hostname used by OAuth callback, logout, and CORS."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+\\.cloudfront\\.net$", var.web_hostname))
    error_message = "web_hostname must be an AWS CloudFront distribution hostname."
  }
}

variable "resource_server_identifier" {
  description = "Stable OAuth resource server identifier."
  type        = string
  default     = "opcoes-ia"
}

variable "scope_name" {
  description = "OAuth scope required by the API."
  type        = string
  default     = "api"
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
