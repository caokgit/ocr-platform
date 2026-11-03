output "roles" {
  description = "Each role's ARN with the namespace and service account it is for, ready for a Pod Identity association."
  value = {
    for k, r in var.pod_roles : k => {
      arn             = aws_iam_role.pod[k].arn
      namespace       = r.namespace
      service_account = r.service_account
    }
  }
}
