locals {
  alarm_actions = [aws_sns_topic.operations.arn]
  flows         = toset(["intraday", "daily", "alert"])
  source_failures = {
    for pair in setproduct(var.mandatory_sources, ["parcial", "falha", "bloqueado"]) :
    "${pair[0]}-${pair[1]}" => { source = pair[0], status = pair[1] }
  }
  alert_conditions = toset(["ausente", "orfa", "falha", "executando", "calendario"])
  neon_components  = toset(["api", "operations"])
}

resource "aws_sns_topic" "operations" {
  name              = "${var.name_prefix}-alarms"
  kms_master_key_id = "alias/aws/sns"
  tags              = var.tags
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "sns" {
  statement {
    sid       = "CloudWatchPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.operations.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }

  statement {
    sid       = "BudgetsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.operations.arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "operations" {
  arn    = aws_sns_topic.operations.arn
  policy = data.aws_iam_policy_document.sns.json
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

resource "aws_cloudwatch_log_metric_filter" "ecs_task_failure" {
  name           = "${var.name_prefix}-ecs-task-failure"
  log_group_name = var.task_state_log_group_name
  pattern        = "{ ($.detail.lastStatus = \"STOPPED\") && (($.detail.stopCode = \"TaskFailedToStart\") || ($.detail.containers[0].exitCode != 0)) }"

  metric_transformation {
    name      = "EcsTaskFailure"
    namespace = "OpcoesIA"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_task_failure" {
  alarm_name          = "${var.name_prefix}-ecs-task-failure"
  alarm_description   = "Fargate task failed to start or exited non-zero; inspect task-state logs."
  namespace           = "OpcoesIA"
  metric_name         = "EcsTaskFailure"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "scheduler_target_error" {
  alarm_name          = "${var.name_prefix}-scheduler-target-error"
  alarm_description   = "EventBridge Scheduler could not deliver RunTask."
  namespace           = "AWS/Scheduler"
  metric_name         = "TargetErrorCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { ScheduleGroup = var.scheduler_group_name }
  alarm_actions       = local.alarm_actions
  tags                = var.tags
}

resource "aws_cloudwatch_metric_alarm" "execution_failure" {
  for_each = local.flows

  alarm_name          = "${var.name_prefix}-${each.key}-failure"
  alarm_description   = "${each.key} execution finished as failure."
  namespace           = "OpcoesIA"
  metric_name         = "ExecutionCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    environment = var.environment
    component   = "operations"
    flow        = each.key
    status      = "falhou"
  }
  alarm_actions = local.alarm_actions
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "source_failure" {
  for_each = local.source_failures

  alarm_name          = "${var.name_prefix}-source-${each.key}"
  alarm_description   = "Mandatory source ${each.value.source} ended ${each.value.status}."
  namespace           = "OpcoesIA"
  metric_name         = "SourceCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    environment = var.environment
    component   = "operations"
    source      = each.value.source
    status      = each.value.status
  }
  alarm_actions = local.alarm_actions
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "operational_alert" {
  for_each = local.alert_conditions

  alarm_name          = "${var.name_prefix}-daily-${each.key}"
  alarm_description   = "Independent alert classified the daily pipeline as ${each.key}."
  namespace           = "OpcoesIA"
  metric_name         = "OperationalAlertCount"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    environment = var.environment
    component   = "operations"
    flow        = "daily"
    condition   = each.key
  }
  alarm_actions = local.alarm_actions
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "neon_connection" {
  for_each = local.neon_components

  alarm_name          = "${var.name_prefix}-${each.key}-neon-connection"
  alarm_description   = "${each.key} observed a Neon connection error."
  namespace           = "OpcoesIA"
  metric_name         = "NeonConnectionError"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    environment = var.environment
    component   = each.key
    dependency  = "neon"
    status      = "falha"
  }
  alarm_actions = local.alarm_actions
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name_prefix}-api-5xx"
  alarm_description   = "HTTP API returned one or more 5xx responses."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    ApiId = var.api_id
    Stage = var.api_stage_name
  }
  alarm_actions = local.alarm_actions
  tags          = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${var.name_prefix}-api-p95-latency"
  alarm_description   = "HTTP API p95 latency exceeded five seconds."
  namespace           = "AWS/ApiGateway"
  metric_name         = "Latency"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    ApiId = var.api_id
    Stage = var.api_stage_name
  }
  alarm_actions = local.alarm_actions
  tags          = var.tags
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.operations.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.operations.arn]
  }

  depends_on = [aws_sns_topic_policy.operations]
}
