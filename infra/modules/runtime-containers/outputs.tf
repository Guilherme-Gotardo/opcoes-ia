output "container_arns" {
  description = "Secrets Manager container ARNs by runtime; values are not managed or exposed."
  value       = { for runtime, container in aws_secretsmanager_secret.runtime : runtime => container.arn }
}
