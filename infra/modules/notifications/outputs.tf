output "identity_arn" {
  description = "Verified sending identity; the send-only policy is scoped to it."
  value       = aws_sesv2_email_identity.sender.arn
}

output "identity_verified_for_sending" {
  description = "False until the confirmation link sent by AWS is followed."
  value       = aws_sesv2_email_identity.sender.verified_for_sending_status
}

output "smtp_user_name" {
  description = "IAM user whose out-of-band access key becomes the SMTP credential."
  value       = aws_iam_user.smtp.name
}

output "smtp_user_arn" {
  description = "Send-only principal ARN; carries no credential value."
  value       = aws_iam_user.smtp.arn
}
