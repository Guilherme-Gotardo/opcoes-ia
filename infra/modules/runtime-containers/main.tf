locals {
  runtimes = toset(["api", "operations"])
}

# Values are populated out of band. Terraform owns only the two low-cost
# containers and never creates an aws_secretsmanager_secret_version resource.
resource "aws_secretsmanager_secret" "runtime" {
  for_each = local.runtimes

  name                    = "${var.name_prefix}/${each.key}"
  description             = "JSON runtime configuration for ${each.key}; value managed outside Terraform"
  recovery_window_in_days = 7

  tags = merge(var.tags, { Runtime = each.key })
}
