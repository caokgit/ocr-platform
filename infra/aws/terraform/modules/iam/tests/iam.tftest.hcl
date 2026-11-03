mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/ocr-platform-dev-mock" }
  }
}

variables {
  name = "ocr-platform-dev"
  pod_roles = {
    external-secrets = {
      namespace       = "external-secrets"
      service_account = "external-secrets"
      policy_json = jsonencode({
        Version   = "2012-10-17"
        Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = "*" }]
      })
    }
  }
}

run "role_trusts_pod_identity_only" {
  command = apply

  assert {
    condition     = jsondecode(aws_iam_role.pod["external-secrets"].assume_role_policy).Statement[0].Principal.Service == "pods.eks.amazonaws.com"
    error_message = "Only EKS Pod Identity may assume the role."
  }

  assert {
    condition     = output.roles["external-secrets"].service_account == "external-secrets"
    error_message = "The output carries the service account for the association."
  }
}

run "allow_star_is_rejected" {
  command = plan

  variables {
    pod_roles = {
      admin = {
        namespace       = "default"
        service_account = "default"
        policy_json = jsonencode({
          Version   = "2012-10-17"
          Statement = [{ Effect = "Allow", Action = "*", Resource = "*" }]
        })
      }
    }
  }

  expect_failures = [var.pod_roles]
}
