output "ecr_repository_arns" {
  description = "Immutable ECR repository ARNs by runtime."
  value       = module.ecr.repository_arns
}

output "ecr_repository_urls" {
  description = "ECR repository URLs by runtime. Deployments must append an image digest."
  value       = module.ecr.repository_urls
}

output "runtime_container_arns" {
  description = "References to the two empty-at-provisioning runtime containers."
  value       = module.runtime_containers.container_arns
}

output "frontend_bucket_name" {
  description = "Private S3 origin populated by the frontend workflow."
  value       = module.frontend.bucket_name
}

output "frontend_distribution_id" {
  description = "CloudFront distribution invalidated after frontend publication."
  value       = module.frontend.distribution_id
}

output "frontend_domain_name" {
  description = "Public CloudFront hostname used by browser and Cognito."
  value       = module.frontend.distribution_domain_name
}

output "frontend_publish_role_arn" {
  description = "OIDC role trusted only by the opcoes-ia-web production environment."
  value       = module.frontend.github_publish_role_arn
}

output "cognito_issuer" {
  description = "Exact issuer passed to API Gateway and Lambda validation."
  value       = module.cognito.issuer
}

output "cognito_client_id" {
  description = "Public web client accepted by the API."
  value       = module.cognito.client_id
}

output "cognito_required_scope" {
  description = "OAuth scope required by protected API routes."
  value       = module.cognito.required_scope
}

output "cognito_hosted_ui_base_url" {
  description = "AWS-managed login domain used by the CloudFront PKCE flow."
  value       = module.cognito.hosted_ui_base_url
}

output "api_endpoint" {
  description = "Regional execute-api endpoint protected by Cognito JWT."
  value       = module.api.api_endpoint
}

output "operations_run_task_network" {
  description = "Public-IP-compatible network values for later disabled schedules."
  value       = module.operations.public_network_configuration
}

output "disabled_schedule_arns" {
  description = "Operational schedules remain disabled until the cutover gate."
  value       = module.scheduling.schedule_arns
}

output "task_state_log_group_name" {
  description = "Captures ECS stops even if the application never reaches Neon."
  value       = module.scheduling.task_state_log_group_name
}

output "alarm_sns_topic_arn" {
  description = "Independent SNS topic used by CloudWatch and AWS Budgets."
  value       = module.observability.sns_topic_arn
}

output "cloudwatch_alarm_names" {
  description = "Actionable alarms for API, tasks, sources, Neon, and absence."
  value       = module.observability.alarm_names
}

output "monthly_budget_name" {
  description = "Monthly actual and forecasted AWS cost budget."
  value       = module.observability.budget_name
}
