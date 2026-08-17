locals {
  callback_url   = "https://${var.web_hostname}/auth/callback"
  logout_url     = "https://${var.web_hostname}/"
  required_scope = "${var.resource_server_identifier}/${var.scope_name}"
}

resource "aws_cognito_user_pool" "api" {
  name                     = "${var.name_prefix}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "ON"
  deletion_protection      = "ACTIVE"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  username_configuration {
    case_sensitive = false
  }

  user_attribute_update_settings {
    attributes_require_verification_before_update = ["email"]
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = var.tags
}

resource "aws_cognito_resource_server" "api" {
  identifier   = var.resource_server_identifier
  name         = "${var.name_prefix}-api"
  user_pool_id = aws_cognito_user_pool.api.id

  scope {
    scope_name        = var.scope_name
    scope_description = "Access the personal portfolio API"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.name_prefix}-web"
  user_pool_id = aws_cognito_user_pool.api.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes = [
    "openid",
    "email",
    "profile",
    local.required_scope,
  ]
  callback_urls                 = [local.callback_url]
  logout_urls                   = [local.logout_url]
  supported_identity_providers  = ["COGNITO"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  explicit_auth_flows           = ["ALLOW_REFRESH_TOKEN_AUTH"]

  auth_session_validity  = 3
  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  depends_on = [aws_cognito_resource_server.api]
}

resource "aws_cognito_user_pool_domain" "managed" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.api.id
}
