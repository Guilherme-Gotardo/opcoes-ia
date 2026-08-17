provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Environment = "bootstrap"
      ManagedBy   = "terraform"
      Project     = var.project_name
      Repository  = var.github_repository
    }
  }
}

locals {
  state_bucket_name = "${var.project_name}-terraform-state-${var.aws_account_id}"
  prod_state_key    = "environments/prod/terraform.tfstate"
  ecr_repository_arns = [
    "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.project_name}-prod-api",
    "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${var.project_name}-prod-operations",
  ]
  frontend_bucket_arn = "arn:aws:s3:::${var.project_name}-prod-web-${var.aws_account_id}"
  frontend_cloudfront_arns = [
    "arn:aws:cloudfront::${var.aws_account_id}:distribution/*",
    "arn:aws:cloudfront::${var.aws_account_id}:cache-policy/*",
    "arn:aws:cloudfront::${var.aws_account_id}:origin-access-control/*",
  ]
  github_oidc_provider_arn = "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
  api_gateway_arns = [
    "arn:aws:apigateway:${var.aws_region}::/apis*",
  ]
  ecs_resource_arns = [
    "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:cluster/${var.project_name}-prod-operations",
    "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${var.project_name}-prod-operations:*",
  ]
  iam_runtime_arns = [
    "arn:aws:iam::${var.aws_account_id}:role/${var.project_name}-prod-api-runtime",
    "arn:aws:iam::${var.aws_account_id}:role/${var.project_name}-prod-operations-execution",
    "arn:aws:iam::${var.aws_account_id}:role/${var.project_name}-prod-operations-task",
    "arn:aws:iam::${var.aws_account_id}:role/${var.project_name}-prod-scheduler",
    "arn:aws:iam::${var.aws_account_id}:role/${var.project_name}-prod-github-web-publish",
  ]
  lambda_arns = ["arn:aws:lambda:${var.aws_region}:${var.aws_account_id}:function:${var.project_name}-prod-api"]
  cognito_user_pool_arns = [
    "arn:aws:cognito-idp:${var.aws_region}:${var.aws_account_id}:userpool/*",
  ]
  log_group_arns = [
    "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${var.project_name}-prod-api*",
    "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/ecs/${var.project_name}-prod-operations*",
    "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/events/${var.project_name}-prod-task-state*",
  ]
  scheduler_arns = [
    "arn:aws:scheduler:${var.aws_region}:${var.aws_account_id}:schedule-group/${var.project_name}-prod-operations",
    "arn:aws:scheduler:${var.aws_region}:${var.aws_account_id}:schedule/${var.project_name}-prod-operations/*",
  ]
  task_event_rule_arns = [
    "arn:aws:events:${var.aws_region}:${var.aws_account_id}:rule/${var.project_name}-prod-task-stopped",
  ]
  alarm_arns = [
    "arn:aws:cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:${var.project_name}-prod-*",
  ]
  sns_topic_arns = [
    "arn:aws:sns:${var.aws_region}:${var.aws_account_id}:${var.project_name}-prod-alarms",
  ]
  budget_arns = [
    "arn:aws:budgets::${var.aws_account_id}:budget/${var.project_name}-prod-monthly",
  ]
  runtime_container_arns = [
    "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}/prod/api-*",
    "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${var.project_name}/prod/operations-*",
  ]
  github_subjects = {
    plan      = "repo:${var.github_repository}:pull_request"
    publish   = "repo:${var.github_repository}:environment:${var.github_environment}"
    migration = "repo:${var.github_repository}:environment:${var.github_environment}"
    deploy    = "repo:${var.github_repository}:environment:${var.github_environment}"
  }
}

# checkov:skip=CKV_AWS_18:State access is audited by IAM/CloudTrail; a second logging bucket is outside this bootstrap.
# checkov:skip=CKV_AWS_144:This personal single-region deployment has versioned state and no cross-region DR requirement.
# checkov:skip=CKV_AWS_145:SSE-S3 is the required encryption mode; no customer-managed key material is needed.
# checkov:skip=CKV2_AWS_61:State versions are intentionally retained rather than expired automatically.
# checkov:skip=CKV2_AWS_62:State changes do not require S3 event notifications.
resource "aws_s3_bucket" "terraform_state" {
  bucket        = local.state_bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "state_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.terraform_state.arn,
      "${aws_s3_bucket.terraform_state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = data.aws_iam_policy_document.state_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.terraform_state]
}

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_trust" {
  for_each = local.github_subjects

  statement {
    sid     = "GitHubActions"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [each.value]
    }
  }
}

resource "aws_iam_role" "github" {
  for_each = local.github_subjects

  name                 = "${var.project_name}-prod-github-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.github_trust[each.key].json
  max_session_duration = 3600

  tags = {
    Purpose = "github-${each.key}"
  }
}

data "aws_iam_policy_document" "plan" {
  # STS does not support resource-level authorization for caller identity.
  statement {
    sid       = "IdentifyPlanningSession"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }

  statement {
    sid       = "ListProductionState"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.terraform_state.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        local.prod_state_key,
        "${local.prod_state_key}.tflock",
      ]
    }
  }

  statement {
    sid     = "ReadProductionState"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.terraform_state.arn}/${local.prod_state_key}",
      "${aws_s3_bucket.terraform_state.arn}/${local.prod_state_key}.tflock",
    ]
  }

  statement {
    sid     = "LockProductionStateForPlan"
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${aws_s3_bucket.terraform_state.arn}/${local.prod_state_key}.tflock",
    ]
  }

  statement {
    sid    = "ReadManagedRepositories"
    effect = "Allow"
    actions = [
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetLifecyclePolicy",
      "ecr:GetRepositoryPolicy",
      "ecr:ListTagsForResource",
    ]
    resources = local.ecr_repository_arns
  }

  # These describe/list APIs either do not support resource ARNs or need the
  # collection endpoint to discover IDs before Terraform can refresh state.
  statement {
    sid    = "DiscoverManagedAwsResources"
    effect = "Allow"
    actions = [
      "apigateway:GET",
      "cognito-idp:DescribeUserPoolDomain",
      "cognito-idp:ListUserPools",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeInternetGateways",
      "ec2:DescribeRouteTables",
      "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
      "ecs:DescribeClusters",
      "ecs:DescribeTaskDefinition",
      "ecs:ListTagsForResource",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "lambda:GetFunction",
      "lambda:GetFunctionConcurrency",
      "lambda:GetPolicy",
      "lambda:ListTags",
      "logs:DescribeLogGroups",
      "logs:DescribeMetricFilters",
      "logs:DescribeResourcePolicies",
      "logs:ListTagsForResource",
      "events:ListRules",
      "scheduler:ListScheduleGroups",
      "scheduler:ListSchedules",
      "cloudwatch:DescribeAlarms",
      "sns:GetSubscriptionAttributes",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadManagedIdentity"
    effect = "Allow"
    actions = [
      "cognito-idp:DescribeResourceServer",
      "cognito-idp:DescribeUserPool",
      "cognito-idp:DescribeUserPoolClient",
      "cognito-idp:ListTagsForResource",
    ]
    resources = local.cognito_user_pool_arns
  }

  statement {
    sid       = "ReadGitHubOidcProvider"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = [local.github_oidc_provider_arn]
  }

  statement {
    sid    = "ReadFrontendBucket"
    effect = "Allow"
    actions = [
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:ListBucket",
    ]
    resources = [local.frontend_bucket_arn]
  }

  statement {
    sid    = "ReadFrontendDistribution"
    effect = "Allow"
    actions = [
      "cloudfront:GetCachePolicy",
      "cloudfront:GetDistribution",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:ListTagsForResource",
    ]
    resources = local.frontend_cloudfront_arns
  }

  statement {
    sid    = "ReadManagedSchedules"
    effect = "Allow"
    actions = [
      "scheduler:GetSchedule",
      "scheduler:GetScheduleGroup",
      "scheduler:ListTagsForResource",
    ]
    resources = local.scheduler_arns
  }

  statement {
    sid    = "ReadTaskStateCapture"
    effect = "Allow"
    actions = [
      "events:DescribeRule",
      "events:ListTagsForResource",
      "events:ListTargetsByRule",
    ]
    resources = local.task_event_rule_arns
  }

  statement {
    sid    = "ReadManagedObservability"
    effect = "Allow"
    actions = [
      "cloudwatch:ListTagsForResource",
    ]
    resources = local.alarm_arns
  }

  statement {
    sid    = "ReadAlarmTopic"
    effect = "Allow"
    actions = [
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
    ]
    resources = local.sns_topic_arns
  }

  statement {
    sid       = "ReadMonthlyBudget"
    effect    = "Allow"
    actions   = ["budgets:ViewBudget"]
    resources = local.budget_arns
  }

  statement {
    sid    = "ReadRuntimeContainersWithoutValues"
    effect = "Allow"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:ListSecretVersionIds",
      "secretsmanager:ListTagsForResource",
    ]
    resources = local.runtime_container_arns
  }
}

resource "aws_iam_role_policy" "plan" {
  name   = "terraform-plan"
  role   = aws_iam_role.github["plan"].id
  policy = data.aws_iam_policy_document.plan.json
}

data "aws_iam_policy_document" "publish" {
  statement {
    sid       = "AuthenticateToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PublishAndInspectImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImageScanFindings",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = local.ecr_repository_arns
  }
}

resource "aws_iam_role_policy" "publish" {
  name   = "publish-images"
  role   = aws_iam_role.github["publish"].id
  policy = data.aws_iam_policy_document.publish.json
}

data "aws_iam_policy_document" "deploy" {
  # STS has no resource-level ARN for GetCallerIdentity.
  statement {
    sid       = "IdentifyDeploySession"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }

  statement {
    sid       = "ListProductionState"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.terraform_state.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        local.prod_state_key,
        "${local.prod_state_key}.tflock",
      ]
    }
  }

  statement {
    sid     = "ManageProductionState"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${aws_s3_bucket.terraform_state.arn}/${local.prod_state_key}",
      "${aws_s3_bucket.terraform_state.arn}/${local.prod_state_key}.tflock",
    ]
  }

  statement {
    sid    = "ManageProjectRepositories"
    effect = "Allow"
    actions = [
      "ecr:CreateRepository",
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepository",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetLifecyclePolicy",
      "ecr:GetRepositoryPolicy",
      "ecr:ListTagsForResource",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutImageTagMutability",
      "ecr:PutLifecyclePolicy",
      "ecr:SetRepositoryPolicy",
      "ecr:TagResource",
      "ecr:UntagResource",
    ]
    resources = local.ecr_repository_arns
  }

  statement {
    sid    = "CreateFrontendDistribution"
    effect = "Allow"
    actions = [
      "cloudfront:CreateCachePolicy",
      "cloudfront:CreateDistribution",
      "cloudfront:CreateOriginAccessControl",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageFrontendDistribution"
    effect = "Allow"
    actions = [
      "cloudfront:DeleteCachePolicy",
      "cloudfront:DeleteDistribution",
      "cloudfront:DeleteOriginAccessControl",
      "cloudfront:GetCachePolicy",
      "cloudfront:GetDistribution",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:ListTagsForResource",
      "cloudfront:TagResource",
      "cloudfront:UntagResource",
      "cloudfront:UpdateCachePolicy",
      "cloudfront:UpdateDistribution",
      "cloudfront:UpdateOriginAccessControl",
    ]
    resources = local.frontend_cloudfront_arns
  }

  statement {
    sid    = "ManageFrontendBucket"
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:ListBucket",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
    ]
    resources = [local.frontend_bucket_arn]
  }

  statement {
    sid       = "ReadGitHubOidcProvider"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = [local.github_oidc_provider_arn]
  }

  # A User Pool has no ARN before creation; all subsequent identity mutations
  # are constrained to pools owned by this account and region below.
  statement {
    sid    = "CreateAndDiscoverProjectIdentity"
    effect = "Allow"
    actions = [
      "cognito-idp:CreateUserPool",
      "cognito-idp:DescribeUserPoolDomain",
      "cognito-idp:ListUserPools",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageProjectIdentity"
    effect = "Allow"
    actions = [
      "cognito-idp:CreateResourceServer",
      "cognito-idp:CreateUserPoolClient",
      "cognito-idp:CreateUserPoolDomain",
      "cognito-idp:DeleteResourceServer",
      "cognito-idp:DeleteUserPool",
      "cognito-idp:DeleteUserPoolClient",
      "cognito-idp:DeleteUserPoolDomain",
      "cognito-idp:DescribeResourceServer",
      "cognito-idp:DescribeUserPool",
      "cognito-idp:DescribeUserPoolClient",
      "cognito-idp:ListTagsForResource",
      "cognito-idp:SetUserPoolMfaConfig",
      "cognito-idp:TagResource",
      "cognito-idp:UntagResource",
      "cognito-idp:UpdateResourceServer",
      "cognito-idp:UpdateUserPool",
      "cognito-idp:UpdateUserPoolClient",
    ]
    resources = local.cognito_user_pool_arns
  }

  # API Gateway v2 authorizes its control plane by REST path; these paths are
  # limited to APIs and custom domains in the configured region.
  statement {
    sid    = "ManageProjectHttpApi"
    effect = "Allow"
    actions = [
      "apigateway:DELETE",
      "apigateway:GET",
      "apigateway:PATCH",
      "apigateway:POST",
      "apigateway:PUT",
    ]
    resources = local.api_gateway_arns
  }

  # EC2 creation and describe APIs used here cannot be scoped to a not-yet
  # allocated VPC/subnet/route/security-group ARN.
  statement {
    sid    = "ManageOperationsNetwork"
    effect = "Allow"
    actions = [
      "ec2:AssociateRouteTable",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:CreateInternetGateway",
      "ec2:CreateRoute",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
      "ec2:CreateTags",
      "ec2:CreateVpc",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteTags",
      "ec2:DeleteVpc",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeInternetGateways",
      "ec2:DescribeRouteTables",
      "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
      "ec2:DetachInternetGateway",
      "ec2:DisassociateRouteTable",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:RevokeSecurityGroupEgress",
    ]
    resources = ["*"]
  }

  # Cluster creation and task-definition registration have no resource ARN at
  # authorization time; mutation after creation is constrained below.
  statement {
    sid    = "CreateOperationsCompute"
    effect = "Allow"
    actions = [
      "ecs:CreateCluster",
      "ecs:DescribeClusters",
      "ecs:DescribeTaskDefinition",
      "ecs:ListTagsForResource",
      "ecs:RegisterTaskDefinition",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageOperationsCompute"
    effect = "Allow"
    actions = [
      "ecs:DeleteCluster",
      "ecs:DeregisterTaskDefinition",
      "ecs:PutClusterCapacityProviders",
      "ecs:TagResource",
      "ecs:UntagResource",
      "ecs:UpdateClusterSettings",
    ]
    resources = local.ecs_resource_arns
  }

  statement {
    sid    = "ManageRuntimeRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:PassRole",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
    ]
    resources = local.iam_runtime_arns
  }

  statement {
    sid    = "ManageApiLambda"
    effect = "Allow"
    actions = [
      "lambda:AddPermission",
      "lambda:CreateFunction",
      "lambda:DeleteFunction",
      "lambda:GetFunction",
      "lambda:GetFunctionConcurrency",
      "lambda:GetPolicy",
      "lambda:ListTags",
      "lambda:PutFunctionConcurrency",
      "lambda:RemovePermission",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]
    resources = local.lambda_arns
  }

  statement {
    sid    = "ManageRuntimeLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DeleteMetricFilter",
      "logs:ListTagsForResource",
      "logs:PutMetricFilter",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
    ]
    resources = local.log_group_arns
  }

  statement {
    sid    = "ManageCloudWatchAlarms"
    effect = "Allow"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = local.alarm_arns
  }

  statement {
    sid    = "ManageAlarmTopic"
    effect = "Allow"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = local.sns_topic_arns
  }

  # Subscription ARNs are allocated only after Subscribe and cannot be scoped
  # to the topic ARN for these two APIs.
  statement {
    sid    = "ManageAlarmEmailSubscription"
    effect = "Allow"
    actions = [
      "sns:GetSubscriptionAttributes",
      "sns:Unsubscribe",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManageMonthlyBudget"
    effect = "Allow"
    actions = [
      "budgets:CreateBudget",
      "budgets:DeleteBudget",
      "budgets:ModifyBudget",
      "budgets:ViewBudget",
    ]
    resources = local.budget_arns
  }

  statement {
    sid    = "ManageSchedules"
    effect = "Allow"
    actions = [
      "scheduler:CreateSchedule",
      "scheduler:CreateScheduleGroup",
      "scheduler:DeleteSchedule",
      "scheduler:DeleteScheduleGroup",
      "scheduler:GetSchedule",
      "scheduler:GetScheduleGroup",
      "scheduler:ListTagsForResource",
      "scheduler:TagResource",
      "scheduler:UntagResource",
      "scheduler:UpdateSchedule",
    ]
    resources = local.scheduler_arns
  }

  statement {
    sid    = "ManageTaskStateCapture"
    effect = "Allow"
    actions = [
      "events:DeleteRule",
      "events:DescribeRule",
      "events:DisableRule",
      "events:EnableRule",
      "events:ListTagsForResource",
      "events:ListTargetsByRule",
      "events:PutRule",
      "events:PutTargets",
      "events:RemoveTargets",
      "events:TagResource",
      "events:UntagResource",
    ]
    resources = local.task_event_rule_arns
  }

  # CloudWatch Logs resource policies are account-scoped and have no resource
  # ARN. This exact policy is used only for EventBridge task-state delivery.
  statement {
    sid    = "ManageEventLogDeliveryPolicy"
    effect = "Allow"
    actions = [
      "logs:DeleteResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:PutResourcePolicy",
    ]
    resources = ["*"]
  }

  # DescribeLogGroups does not support resource-level authorization.
  statement {
    sid    = "DiscoverRuntimeLogs"
    effect = "Allow"
    actions = [
      "events:ListRules",
      "cloudwatch:DescribeAlarms",
      "logs:DescribeLogGroups",
      "logs:DescribeMetricFilters",
      "scheduler:ListScheduleGroups",
      "scheduler:ListSchedules",
      "sns:GetSubscriptionAttributes",
    ]
    resources = ["*"]
  }

  # CreateSecret cannot target an ARN that does not exist. The role can create
  # containers only with the project path; values remain out of Terraform.
  statement {
    sid       = "CreateRuntimeContainers"
    effect    = "Allow"
    actions   = ["secretsmanager:CreateSecret"]
    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "secretsmanager:Name"
      values   = ["${var.project_name}/prod/*"]
    }
  }

  statement {
    sid    = "ManageRuntimeContainersWithoutValues"
    effect = "Allow"
    actions = [
      "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:ListSecretVersionIds",
      "secretsmanager:ListTagsForResource",
      "secretsmanager:RestoreSecret",
      "secretsmanager:TagResource",
      "secretsmanager:UntagResource",
      "secretsmanager:UpdateSecret",
    ]
    resources = local.runtime_container_arns
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "terraform-deploy"
  role   = aws_iam_role.github["deploy"].id
  policy = data.aws_iam_policy_document.deploy.json
}

# The migration role intentionally has no AWS data-plane permissions. Its
# administrative Neon URL belongs to the protected GitHub environment.
