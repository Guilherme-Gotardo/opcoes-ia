variable "name_prefix" {
  description = "Prefix used by alarms, SNS, and Budget."
  type        = string
}

variable "environment" {
  description = "Environment dimension emitted by application EMF."
  type        = string
}

variable "api_id" {
  description = "HTTP API identifier used by AWS/ApiGateway metrics."
  type        = string
}

variable "api_stage_name" {
  description = "HTTP API stage dimension."
  type        = string
  default     = "$default"
}

variable "task_state_log_group_name" {
  description = "Log group receiving ECS Task State Change events."
  type        = string
}

variable "scheduler_group_name" {
  description = "Scheduler group dimension used by delivery alarms."
  type        = string
}

variable "notification_email" {
  description = "Email endpoint for operational and budget SNS notifications."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly actual and forecasted AWS cost threshold."
  type        = number
}

variable "mandatory_sources" {
  description = "Collection sources whose degraded state must alarm."
  type        = set(string)
  default     = ["brapi", "earnings"]
}

variable "tags" {
  description = "Cost and ownership tags for supported resources."
  type        = map(string)
  default     = {}
}
