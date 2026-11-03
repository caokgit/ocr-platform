# One IAM role per workload, assumable only through EKS Pod Identity: the pod's service account is the identity.
resource "aws_iam_role" "pod" {
  for_each = var.pod_roles

  name        = "${var.name}-${each.key}"
  description = "Pod Identity role for ${each.value.namespace}/${each.value.service_account}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "pod" {
  for_each = var.pod_roles

  name   = each.key
  role   = aws_iam_role.pod[each.key].id
  policy = each.value.policy_json
}
