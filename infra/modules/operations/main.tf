locals {
  cluster_name = "${var.name_prefix}-operations"
  image_uri    = "${var.image_repository_url}@${var.image_digest}"
  runtime_keys = toset([
    "ANTHROPIC_API_KEY",
    "BRAPI_TOKEN",
    "DATABASE_URL",
    "NEWS_API_KEY",
    "OPLAB_TOKEN",
    "SMTP_PASSWORD",
  ])
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "operations" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(var.tags, { Name = "${local.cluster_name}-vpc" })
}

resource "aws_internet_gateway" "operations" {
  vpc_id = aws_vpc.operations.id
  tags   = merge(var.tags, { Name = "${local.cluster_name}-igw" })
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.operations.id
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 2, count.index)
  map_public_ip_on_launch = true

  tags = merge(var.tags, { Name = "${local.cluster_name}-public-${count.index + 1}" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.operations.id
  tags   = merge(var.tags, { Name = "${local.cluster_name}-public" })
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.operations.id
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "tasks" {
  name        = "${local.cluster_name}-egress"
  description = "No ingress; outbound TLS, Neon and configured SMTP only"
  vpc_id      = aws_vpc.operations.id

  tags = merge(var.tags, { Name = "${local.cluster_name}-egress" })
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.tasks.id
  description       = "HTTPS providers and AWS APIs"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "neon" {
  security_group_id = aws_security_group.tasks.id
  description       = "TLS PostgreSQL to Neon"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "smtp" {
  security_group_id = aws_security_group.tasks.id
  description       = "Optional STARTTLS notification delivery"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = var.smtp_port
  to_port           = var.smtp_port
  ip_protocol       = "tcp"
}

resource "aws_ecs_cluster" "operations" {
  name = local.cluster_name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = var.tags
}

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.cluster_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = var.tags
}

resource "aws_iam_role" "task" {
  name               = "${local.cluster_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "AuthenticateToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullOperationsImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [var.image_repository_arn]
  }

  statement {
    sid       = "ReadOperationsRuntimeContainer"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.runtime_container_arn]
  }

  statement {
    sid    = "WriteOperationsLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.operations.arn}:*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "execution-minimum"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# checkov:skip=CKV_AWS_158:AWS-managed CloudWatch encryption avoids a dedicated KMS key and fixed administration for personal logs.
resource "aws_cloudwatch_log_group" "operations" {
  name              = "/ecs/${local.cluster_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_ecs_task_definition" "operations" {
  family                   = local.cluster_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name      = "operations"
    image     = local.image_uri
    essential = true
    command   = ["--help"]
    environment = [
      { name = "BRAPI_REQUESTS_DIA_MAXIMO", value = tostring(var.brapi_daily_limit) },
      { name = "OPCOES_IA_ENV", value = "prod" },
      { name = "OPCOES_IA_COMPONENT", value = "operations" },
      { name = "SMTP_FROM", value = var.smtp_from },
      { name = "SMTP_HOST", value = var.smtp_host },
      { name = "SMTP_PORT", value = tostring(var.smtp_port) },
      { name = "SMTP_STARTTLS", value = "true" },
      { name = "SMTP_TO", value = var.smtp_to },
      { name = "SMTP_USER", value = var.smtp_user },
    ]
    secrets = [
      for key in sort(tolist(local.runtime_keys)) : {
        name      = key
        valueFrom = "${var.runtime_container_arn}:${key}::"
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.operations.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "task"
      }
    }
  }])

  depends_on = [aws_iam_role_policy.execution]
  tags       = var.tags
}
