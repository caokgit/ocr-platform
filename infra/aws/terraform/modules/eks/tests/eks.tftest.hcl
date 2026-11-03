mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/ocr-platform-dev-mock" }
  }
  mock_resource "aws_eks_cluster" {
    defaults = {
      arn = "arn:aws:eks:ap-southeast-1:123456789012:cluster/ocr-platform-dev"
      # A configured block is mocked one element at a time: an object, holding only the computed attributes.
      vpc_config = {
        cluster_security_group_id = "sg-0123456789abcdef0"
        vpc_id                    = "vpc-0123456789abcdef0"
      }
      certificate_authority = [{ data = "bW9jaw==" }]
    }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}

variables {
  name                 = "ocr-platform-dev"
  subnet_ids           = ["subnet-0000000000000000a", "subnet-0000000000000000b", "subnet-0000000000000000c"]
  public_access_cidrs  = ["203.0.113.0/24"]
  admin_principal_arns = ["arn:aws:iam::123456789012:role/platform-admin"]
  kms_key_arn          = "arn:aws:kms:ap-southeast-1:123456789012:key/00000000-0000-0000-0000-000000000000"
  pod_identities = {
    external-secrets = {
      arn             = "arn:aws:iam::123456789012:role/ocr-platform-dev-external-secrets"
      namespace       = "external-secrets"
      service_account = "external-secrets"
    }
  }
}

run "api_auth_encrypted_secrets_on_demand_system_nodes" {
  command = apply

  assert {
    condition     = aws_eks_cluster.this.access_config[0].authentication_mode == "API"
    error_message = "Access entries only, no aws-auth ConfigMap."
  }

  assert {
    condition     = aws_eks_cluster.this.encryption_config[0].resources == toset(["secrets"])
    error_message = "Kubernetes secrets are envelope-encrypted with the platform key."
  }

  assert {
    condition     = aws_eks_node_group.system.capacity_type == "ON_DEMAND" && aws_eks_node_group.system.scaling_config[0].min_size == 2
    error_message = "System pods run on at least two on-demand nodes."
  }

  assert {
    condition     = contains(keys(aws_eks_addon.before_nodes), "eks-pod-identity-agent")
    error_message = "The Pod Identity agent is installed before any workload needs it."
  }

  assert {
    condition     = one(aws_eks_addon.after_nodes["aws-ebs-csi-driver"].pod_identity_association).service_account == "ebs-csi-controller-sa"
    error_message = "The EBS CSI driver gets its permissions through Pod Identity."
  }

  assert {
    condition     = aws_eks_pod_identity_association.this["external-secrets"].namespace == "external-secrets"
    error_message = "Each pod identity is associated with its namespace and service account."
  }
}

run "private_only_endpoint" {
  command = plan

  variables {
    public_access_cidrs = []
  }

  assert {
    condition     = !aws_eks_cluster.this.vpc_config[0].endpoint_public_access
    error_message = "No public CIDRs makes the endpoint private only."
  }
}

run "open_api_endpoint_is_rejected" {
  command = plan

  variables {
    public_access_cidrs = ["0.0.0.0/0"]
  }

  expect_failures = [var.public_access_cidrs]
}
