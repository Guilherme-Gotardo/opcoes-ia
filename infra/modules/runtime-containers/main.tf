locals {
  runtimes = toset(["api", "operations"])
}

# Values are populated out of band. Terraform owns only the two low-cost
# containers and never creates an aws_secretsmanager_secret_version resource.
resource "aws_secretsmanager_secret" "runtime" {
  #checkov:skip=CKV_AWS_149:The default AWS-managed Secrets Manager key is sufficient; no customer-managed key material is needed for these runtime containers.
  #checkov:skip=CKV2_AWS_57:Values are heterogeneous application credentials rotated through the documented operational runbook, not by a Secrets Manager rotation Lambda.
  for_each = local.runtimes

  name                    = "${var.name_prefix}/${each.key}"
  description             = "JSON runtime configuration for ${each.key}; value managed outside Terraform"
  recovery_window_in_days = 7

  tags = merge(var.tags, { Runtime = each.key })
}
