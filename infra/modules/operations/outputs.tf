output "cluster_arn" {
  description = "ECS cluster used by later Scheduler targets."
  value       = aws_ecs_cluster.operations.arn
}

output "task_definition_arn" {
  description = "Immutable revision ARN for the operations task definition."
  value       = aws_ecs_task_definition.operations.arn
}

output "public_network_configuration" {
  description = "RunTask network values; callers must keep assign_public_ip ENABLED."
  value = {
    assign_public_ip = "ENABLED"
    security_groups  = [aws_security_group.tasks.id]
    subnets          = aws_subnet.public[*].id
  }
}

output "task_role_arn" {
  description = "Runtime role intentionally carrying no AWS data-plane policy."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "Execution role passed only to the exact operations task definition."
  value       = aws_iam_role.execution.arn
}
