output "state_bucket_name" {
  description = "S3 bucket used by Terraform backends."
  value       = aws_s3_bucket.terraform_state.id
}

output "github_role_arns" {
  description = "Short-lived GitHub Actions roles by responsibility."
  value       = { for purpose, role in aws_iam_role.github : purpose => role.arn }
}
