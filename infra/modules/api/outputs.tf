output "api_endpoint" {
  description = "Regional execute-api endpoint protected by the JWT authorizer."
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "function_arn" {
  description = "Deployed API Lambda ARN."
  value       = aws_lambda_function.api.arn
}

output "http_api_id" {
  description = "HTTP API identifier used by later observability resources."
  value       = aws_apigatewayv2_api.api.id
}

output "stage_name" {
  description = "HTTP API stage used by CloudWatch dimensions."
  value       = aws_apigatewayv2_stage.default.name
}
