variable "name_prefix" {
  description = "Prefix used by Scheduler and task-state resources."
  type        = string
}

variable "cluster_arn" {
  description = "Exact ECS cluster invoked by Scheduler."
  type        = string
}

variable "task_definition_arn" {
  description = "Exact immutable task definition revision invoked by Scheduler."
  type        = string
}

variable "task_role_arn" {
  description = "Exact application task role Scheduler may pass."
  type        = string
}

variable "execution_role_arn" {
  description = "Exact ECS execution role Scheduler may pass."
  type        = string
}

variable "network_configuration" {
  description = "Public egress-only network produced by the operations module."
  type = object({
    assign_public_ip = string
    security_groups  = list(string)
    subnets          = list(string)
  })
}

variable "timezone" {
  description = "IANA timezone interpreted directly by EventBridge Scheduler."
  type        = string
  default     = "America/Sao_Paulo"
}

variable "intraday_expression" {
  description = "Fourteen half-hour weekday triggers from 10:00 through 16:30."
  type        = string
  default     = "cron(0/30 10-16 ? * MON-FRI *)"
}

variable "daily_expression" {
  description = "Daily report flow after market close."
  type        = string
  default     = "cron(10 17 ? * MON-FRI *)"
}

variable "alert_expression" {
  description = "Independent missing-pipeline alert after market close."
  type        = string
  default     = "cron(30 18 ? * MON-FRI *)"
}

variable "log_retention_days" {
  description = "Finite retention for ECS task-state events."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied in addition to provider default tags."
  type        = map(string)
  default     = {}
}
