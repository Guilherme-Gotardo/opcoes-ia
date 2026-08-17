# Outbound email for the daily report and the independent pipeline alert.
#
# Terraform owns the verified identity and the send-only principal. It never
# owns a credential value: no aws_iam_access_key resource exists here, because
# its ses_smtp_password_v4 attribute would land in the state file in clear
# text. The access key is created out of band and its derived SMTP password is
# written into the operations runtime container, the same way every other
# credential in this project is handled.
#
# Verification is asynchronous: creating the identity makes AWS send a
# confirmation link to the address, and verified_for_sending_status stays false
# until a human follows it. Sending before that fails explicitly.

resource "aws_sesv2_email_identity" "sender" {
  email_identity = var.sender_address

  tags = merge(var.tags, { Name = "${var.name_prefix}-sender" })
}

# force_destroy is required precisely because the access key is created out of
# band: without it, deleting this user fails while a key Terraform never saw
# still exists, and the documented rollback would stall.
resource "aws_iam_user" "smtp" {
  #checkov:skip=CKV_AWS_273:Amazon SES SMTP authentication requires a dedicated IAM access-key principal; the user is send-only and created for this channel.
  name          = "${var.name_prefix}-smtp"
  force_destroy = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-smtp" })
}

# The SMTP endpoint submits complete MIME messages, which AWS authorises with
# ses:SendRawEmail; ses:SendEmail would not enable this path. The resource is
# scoped to the single identity, and the FromAddress condition keeps that
# intent explicit if another identity is ever added to this module.
data "aws_iam_policy_document" "send_only" {
  statement {
    sid       = "SendAsVerifiedIdentity"
    effect    = "Allow"
    actions   = ["ses:SendRawEmail"]
    resources = [aws_sesv2_email_identity.sender.arn]

    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.sender_address]
    }
  }
}

resource "aws_iam_user_policy" "send_only" {
  #checkov:skip=CKV_AWS_40:The SES SMTP credential must authorize only its dedicated IAM user; the policy is one action scoped to one verified identity.
  name   = "smtp-send-only"
  user   = aws_iam_user.smtp.name
  policy = data.aws_iam_policy_document.send_only.json
}
