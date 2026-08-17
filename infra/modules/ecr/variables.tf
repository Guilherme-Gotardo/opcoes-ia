variable "repository_names" {
  description = "Immutable ECR repositories keyed by runtime name."
  type        = map(string)

  validation {
    condition = (
      length(var.repository_names) == 2 &&
      length(setsubtract(toset(keys(var.repository_names)), toset(["api", "operations"]))) == 0 &&
      alltrue([for name in values(var.repository_names) : can(regex("^[a-z0-9]+(?:[._/-][a-z0-9]+)*$", name))])
    )
    error_message = "repository_names must contain exactly api and operations with valid ECR names."
  }
}

variable "release_images_to_keep" {
  description = "Number of recent release-tagged digests retained for rollback."
  type        = number
  default     = 10

  validation {
    condition     = var.release_images_to_keep >= 5 && floor(var.release_images_to_keep) == var.release_images_to_keep
    error_message = "Keep at least five whole release images for rollback."
  }
}

variable "untagged_image_days" {
  description = "Days before untagged images are removed."
  type        = number
  default     = 7

  validation {
    condition     = var.untagged_image_days >= 1 && floor(var.untagged_image_days) == var.untagged_image_days
    error_message = "untagged_image_days must be a positive whole number."
  }
}

variable "stale_build_image_days" {
  description = "Days before build- and pr-tagged images are removed."
  type        = number
  default     = 30

  validation {
    condition     = var.stale_build_image_days >= 7 && floor(var.stale_build_image_days) == var.stale_build_image_days
    error_message = "stale_build_image_days must be a whole number of at least seven."
  }
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
