variable "name_prefix" {
  description = "Prefix used by the outbound email identity resources."
  type        = string
}

variable "sender_address" {
  description = "Nonsecret address verified for sending operational email."
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.sender_address))
    error_message = "sender_address must be a single email address."
  }
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
