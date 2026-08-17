locals {
  schedules = {
    intraday = {
      expression             = var.intraday_expression
      maximum_event_age      = 60
      maximum_retry_attempts = 0
    }
    daily = {
      expression             = var.daily_expression
      maximum_event_age      = 1800
      maximum_retry_attempts = 2
    }
    alert = {
      expression             = var.alert_expression
      maximum_event_age      = 1800
      maximum_retry_attempts = 2
    }
  }
}

resource "aws_scheduler_schedule_group" "operations" {
  name = "${var.name_prefix}-operations"
  tags = var.tags
}

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "RunExactOperationsTask"
    effect    = "Allow"
    actions   = ["ecs:RunTask"]
    resources = [var.task_definition_arn]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [var.cluster_arn]
    }
  }

  statement {
    sid       = "PassExactTaskRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [var.task_role_arn, var.execution_role_arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "run-exact-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "flow" {
  for_each = local.schedules

  name                         = "${var.name_prefix}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.operations.name
  description                  = "Disabled-by-default ${each.key} operations flow"
  schedule_expression          = each.value.expression
  schedule_expression_timezone = var.timezone
  state                        = "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = var.cluster_arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      containerOverrides = [{
        name = "operations"
        command = [
          each.key,
          "--window",
          "<aws.scheduler.scheduled-time>",
          "--trigger",
          "eventbridge",
        ]
      }]
    })

    ecs_parameters {
      task_definition_arn = var.task_definition_arn
      launch_type         = "FARGATE"
      platform_version    = "LATEST"
      task_count          = 1

      network_configuration {
        assign_public_ip = var.network_configuration.assign_public_ip == "ENABLED"
        security_groups  = var.network_configuration.security_groups
        subnets          = var.network_configuration.subnets
      }
    }

    retry_policy {
      maximum_event_age_in_seconds = each.value.maximum_event_age
      maximum_retry_attempts       = each.value.maximum_retry_attempts
    }
  }

  depends_on = [aws_iam_role_policy.scheduler]
}

# Captures every stopped task, including launch failures that happen before the
# application can open an execution row in Neon. Metrics/alarms classify exits.
# checkov:skip=CKV_AWS_158:AWS-managed encryption avoids a dedicated KMS key for low-volume operational events.
resource "aws_cloudwatch_log_group" "task_state" {
  name              = "/aws/events/${var.name_prefix}-task-state"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_event_rule" "task_stopped" {
  name        = "${var.name_prefix}-task-stopped"
  description = "Capture ECS task stops even before Neon logging starts"
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [var.cluster_arn]
      lastStatus = ["STOPPED"]
    }
  })
  tags = var.tags
}

resource "aws_cloudwatch_event_target" "task_state_log" {
  rule = aws_cloudwatch_event_rule.task_stopped.name
  arn  = aws_cloudwatch_log_group.task_state.arn
}

data "aws_iam_policy_document" "event_logs" {
  statement {
    sid    = "EventBridgeWriteTaskState"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.task_state.arn}:*"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.task_stopped.arn]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "event_logs" {
  policy_name     = "${var.name_prefix}-event-logs"
  policy_document = data.aws_iam_policy_document.event_logs.json
}
