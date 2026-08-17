output "bucket_name" {
  description = "Private S3 bucket populated by the frontend release."
  value       = aws_s3_bucket.web.id
}

output "distribution_id" {
  description = "CloudFront distribution invalidated after a complete upload."
  value       = aws_cloudfront_distribution.web.id
}

output "distribution_domain_name" {
  description = "Public hostname used by Cognito callback, logout, and API CORS."
  value       = aws_cloudfront_distribution.web.domain_name
}

output "web_origin" {
  description = "Exact HTTPS origin accepted by the hosted API."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "github_publish_role_arn" {
  description = "Short-lived OIDC role trusted only by the frontend repository."
  value       = aws_iam_role.github_publish.arn
}
