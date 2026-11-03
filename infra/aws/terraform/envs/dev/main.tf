data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name        = "ocr-platform-${var.environment}"
  azs         = [for zone in ["a", "b", "c"] : "${var.region}${zone}"]
  secret_path = "ocr-platform/${var.environment}"
  arn_prefix  = "arn:${data.aws_partition.current.partition}"
}

module "kms" {
  source = "../../modules/kms"

  name = local.name
}

module "network" {
  source = "../../modules/network"

  name               = local.name
  region             = var.region
  azs                = local.azs
  single_nat_gateway = var.single_nat_gateway
  kms_key_arn        = module.kms.key_arn
}

module "storage" {
  source = "../../modules/storage"

  bucket_name = "${local.name}-lake-${data.aws_caller_identity.current.account_id}"
  kms_key_arn = module.kms.key_arn
}

# The app's configuration secret; External Secrets copies it into the cluster.
resource "aws_secretsmanager_secret" "podinfo" {
  name                    = "${local.secret_path}/podinfo"
  description             = "podinfo's message, read by External Secrets"
  kms_key_id              = module.kms.key_arn
  recovery_window_in_days = 7
}

module "iam" {
  source = "../../modules/iam"

  name = local.name
  pod_roles = {
    external-secrets = {
      namespace       = "external-secrets"
      service_account = "external-secrets"
      policy_json = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Effect   = "Allow"
            Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
            Resource = "${local.arn_prefix}:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:${local.secret_path}/*"
          },
          {
            Effect    = "Allow"
            Action    = "kms:Decrypt"
            Resource  = module.kms.key_arn
            Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com" } }
          },
        ]
      })
    }
    # cert-manager proves domain ownership with a DNS-01 TXT record in Route 53 for Let's Encrypt.
    cert-manager = {
      namespace       = "cert-manager"
      service_account = "cert-manager"
      policy_json = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Effect   = "Allow"
            Action   = "route53:GetChange"
            Resource = "${local.arn_prefix}:route53:::change/*"
          },
          {
            Effect   = "Allow"
            Action   = ["route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets"]
            Resource = "${local.arn_prefix}:route53:::hostedzone/${var.route53_zone_id}"
          },
          {
            Effect   = "Allow"
            Action   = "route53:ListHostedZonesByName"
            Resource = "*"
          },
        ]
      })
    }
    lake-writer = {
      namespace       = "lab-data"
      service_account = "spark"
      policy_json = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Effect   = "Allow"
            Action   = "s3:ListBucket"
            Resource = module.storage.bucket_arn
          },
          {
            Effect   = "Allow"
            Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
            Resource = "${module.storage.bucket_arn}/*"
          },
          {
            Effect   = "Allow"
            Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
            Resource = module.kms.key_arn
          },
        ]
      })
    }
  }
}

module "eks" {
  source = "../../modules/eks"

  name                 = local.name
  subnet_ids           = module.network.private_subnet_ids
  public_access_cidrs  = var.api_allowed_cidrs
  admin_principal_arns = var.admin_principal_arns
  pod_identities       = module.iam.roles
  kms_key_arn          = module.kms.key_arn
}

module "karpenter" {
  source = "../../modules/karpenter"

  cluster_name = module.eks.cluster_name
}

module "database" {
  source = "../../modules/database"

  name                   = local.name
  vpc_id                 = module.network.vpc_id
  subnet_ids             = module.network.database_subnet_ids
  client_security_groups = { eks-cluster = module.eks.cluster_security_group_id }
  kms_key_arn            = module.kms.key_arn
  multi_az               = var.database_multi_az
}
