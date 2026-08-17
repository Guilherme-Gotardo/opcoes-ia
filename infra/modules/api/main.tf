locals {
  function_name = "${var.name_prefix}-api"
  image_uri     = "${var.image_repository_url}@${var.image_digest}"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.function_name}-runtime"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "ReadApiRuntimeContainer"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.runtime_container_arn]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "runtime-minimum"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_cloudwatch_log_group" "api" {
  #checkov:skip=CKV_AWS_158:AWS-managed CloudWatch encryption avoids a dedicated KMS key and fixed administration for personal logs.
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "api" {
  #checkov:skip=CKV_AWS_272:The immutable image is built and scanned in CI; AWS code-signing would require a separate signing pipeline.
  #checkov:skip=CKV_AWS_116:Synchronous HTTP API requests have no asynchronous destination to drain into a Lambda DLQ.
  #checkov:skip=CKV_AWS_173:The Lambda environment contains ARNs and public configuration only; credentials are fetched from Secrets Manager by the runtime.
  #checkov:skip=CKV_AWS_117:Keeping this lightweight API outside a VPC avoids a NAT gateway; it reaches only public AWS endpoints and the API has no private network dependency.
  #checkov:skip=CKV_AWS_50:X-Ray is not part of the low-volume single-user observability design; structured CloudWatch logs and metrics are used instead.
  function_name = local.function_name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = ["x86_64"]

  memory_size                    = var.memory_size
  timeout                        = var.timeout_seconds
  reserved_concurrent_executions = var.reserved_concurrency

  environment {
    variables = {
      API_RUNTIME_CONFIG_ARN    = var.runtime_container_arn
      BRAPI_REQUESTS_DIA_MAXIMO = tostring(var.brapi_daily_limit)
      COGNITO_CLIENT_ID         = var.cognito_client_id
      COGNITO_ISSUER            = var.cognito_issuer
      COGNITO_REQUIRED_SCOPE    = var.cognito_required_scope
      OPCOES_IA_ENV             = "prod"
      OPCOES_IA_COMPONENT       = "api"
      OPCOES_IA_WEB_ORIGIN      = var.web_origin
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy.lambda,
  ]

  tags = var.tags
}

resource "aws_apigatewayv2_api" "api" {
  name                         = "${var.name_prefix}-http"
  protocol_type                = "HTTP"
  disable_execute_api_endpoint = false

  cors_configuration {
    allow_origins  = [var.web_origin]
    allow_methods  = ["GET", "POST", "OPTIONS"]
    allow_headers  = ["authorization", "content-type", "x-request-id"]
    expose_headers = ["x-request-id"]
    max_age        = 300
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.api.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.name_prefix}-cognito"

  jwt_configuration {
    audience = [var.cognito_client_id]
    issuer   = var.cognito_issuer
  }
}

resource "aws_apigatewayv2_route" "default" {
  api_id               = aws_apigatewayv2_api.api.id
  route_key            = "$default"
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.cognito.id
  authorization_scopes = [var.cognito_required_scope]
}

resource "aws_apigatewayv2_route" "health" {
  #checkov:skip=CKV_AWS_309:Health endpoints are intentionally public so liveness checks do not require Cognito credentials.
  for_each = toset(["GET /health/live", "GET /health/ready"])

  api_id             = aws_apigatewayv2_api.api.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "NONE"
}

# Browsers do not attach the access token to a CORS preflight. Without this
# specific route, the authenticated $default route rejects OPTIONS before the
# API Gateway CORS policy can answer it.
resource "aws_apigatewayv2_route" "preflight" {
  #checkov:skip=CKV_AWS_309:CORS preflight requests cannot carry the access token and must remain unauthenticated.
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = "OPTIONS /{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_stage" "default" {
  #checkov:skip=CKV_AWS_76:Application structured logs and the independent execution log provide the required low-volume operational trail.
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
