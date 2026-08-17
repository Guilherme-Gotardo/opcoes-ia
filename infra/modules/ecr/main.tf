locals {
  lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 10
        description  = "Expire untagged upload remnants"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_image_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 20
        description  = "Expire stale CI build images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["build-"]
          countType     = "sinceImagePushed"
          countUnit     = "days"
          countNumber   = var.stale_build_image_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 30
        description  = "Expire stale pull request images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["pr-"]
          countType     = "sinceImagePushed"
          countUnit     = "days"
          countNumber   = var.stale_build_image_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 40
        description  = "Retain recent immutable releases for digest rollback"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["release-"]
          countType     = "imageCountMoreThan"
          countNumber   = var.release_images_to_keep
        }
        action = { type = "expire" }
      },
    ]
  })
}

# checkov:skip=CKV_AWS_136:AES256 is the selected nonsecret registry encryption mode for this personal deployment.
resource "aws_ecr_repository" "runtime" {
  for_each = var.repository_names

  name                 = each.value
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(var.tags, { Runtime = each.key })
}

resource "aws_ecr_lifecycle_policy" "runtime" {
  for_each = aws_ecr_repository.runtime

  repository = each.value.name
  policy     = local.lifecycle_policy
}
