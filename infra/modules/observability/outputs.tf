output "sns_topic_arn" {
  description = "Independent alarm and Budget notification topic."
  value       = aws_sns_topic.operations.arn
}

output "alarm_names" {
  description = "CloudWatch alarms created for the hosted platform."
  value = concat(
    [
      aws_cloudwatch_metric_alarm.ecs_task_failure.alarm_name,
      aws_cloudwatch_metric_alarm.scheduler_target_error.alarm_name,
      aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.api_latency.alarm_name,
    ],
    values(aws_cloudwatch_metric_alarm.execution_failure)[*].alarm_name,
    values(aws_cloudwatch_metric_alarm.source_failure)[*].alarm_name,
    values(aws_cloudwatch_metric_alarm.operational_alert)[*].alarm_name,
    values(aws_cloudwatch_metric_alarm.neon_connection)[*].alarm_name,
  )
}

output "budget_name" {
  description = "Monthly AWS cost budget with actual and forecasted alerts."
  value       = aws_budgets_budget.monthly.name
}
