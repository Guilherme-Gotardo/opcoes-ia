output "schedule_arns" {
  description = "Disabled schedule ARNs by operational flow."
  value       = { for flow, schedule in aws_scheduler_schedule.flow : flow => schedule.arn }
}

output "task_state_log_group_name" {
  description = "Log group receiving stopped ECS task events."
  value       = aws_cloudwatch_log_group.task_state.name
}

output "task_state_rule_arn" {
  description = "EventBridge rule capturing task stops before Neon logging."
  value       = aws_cloudwatch_event_rule.task_stopped.arn
}

output "schedule_group_name" {
  description = "Scheduler group used by AWS/Scheduler metrics."
  value       = aws_scheduler_schedule_group.operations.name
}
