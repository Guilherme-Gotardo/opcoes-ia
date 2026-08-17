output "repository_arns" {
  description = "Repository ARNs keyed by runtime."
  value       = { for runtime, repository in aws_ecr_repository.runtime : runtime => repository.arn }
}

output "repository_urls" {
  description = "Repository URLs keyed by runtime; releases append an immutable digest."
  value       = { for runtime, repository in aws_ecr_repository.runtime : runtime => repository.repository_url }
}
