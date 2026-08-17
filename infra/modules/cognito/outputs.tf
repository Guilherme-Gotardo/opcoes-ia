output "user_pool_id" {
  description = "User Pool used for the single administrative user."
  value       = aws_cognito_user_pool.api.id
}

output "client_id" {
  description = "Public web app client ID; no client secret is generated."
  value       = aws_cognito_user_pool_client.web.id
}

output "issuer" {
  description = "Exact issuer validated by API Gateway and FastAPI."
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.api.id}"
}

output "required_scope" {
  description = "OAuth scope required on every protected API route."
  value       = local.required_scope
}

output "hosted_ui_base_url" {
  description = "AWS-managed login domain; no custom DNS is required."
  value       = "https://${aws_cognito_user_pool_domain.managed.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "callback_url" {
  description = "PKCE callback coordinated with opcoes-ia-web."
  value       = local.callback_url
}
