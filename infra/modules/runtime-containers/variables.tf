variable "name_prefix" {
  description = "Prefix shared by the two runtime credential containers."
  type        = string
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
