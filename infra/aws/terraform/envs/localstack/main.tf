# The part of the dev design LocalStack's free image can run: network, key, bucket, roles, the Karpenter queue,
# and two things the kind drills read: a secret (External Secrets) and a work queue (KEDA).
locals {
  name = "ocr-platform-ls"
}

module "kms" {
  source = "../../modules/kms"

  name                    = local.name
  deletion_window_in_days = 7
}

module "network" {
  source = "../../modules/network"

  name        = local.name
  region      = "ap-southeast-1"
  azs         = ["ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c"]
  kms_key_arn = module.kms.key_arn
}

module "storage" {
  source = "../../modules/storage"

  bucket_name   = "${local.name}-lake"
  kms_key_arn   = module.kms.key_arn
  force_destroy = true
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
        Statement = [{
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
          Resource = aws_secretsmanager_secret.podinfo.arn
        }]
      })
    }
  }
}

module "karpenter" {
  source = "../../modules/karpenter"

  cluster_name    = local.name
  bind_to_cluster = false
}

resource "aws_secretsmanager_secret" "podinfo" {
  name                    = "ocr-platform/localstack/podinfo"
  description             = "podinfo's message, read by External Secrets on kind"
  kms_key_id              = module.kms.key_arn
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "podinfo" {
  secret_id = aws_secretsmanager_secret.podinfo.id
  secret_string = jsonencode({
    message = "hello from AWS Secrets Manager, version 1"
  })

  # The drill changes the value outside Terraform to show External Secrets picking it up.
  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_sqs_queue" "work" {
  name                       = "${local.name}-work"
  visibility_timeout_seconds = 30
  sqs_managed_sse_enabled    = true
}

# Barman Cloud's target for the database drills (backups and WAL archive), with the lake's controls.
module "pg_backups" {
  source = "../../modules/storage"

  bucket_name   = "${local.name}-pg-backups"
  kms_key_arn   = module.kms.key_arn
  force_destroy = true
}

# The backup bucket was a bare aws_s3_bucket until it moved into the storage module.
moved {
  from = aws_s3_bucket.pg_backups
  to   = module.pg_backups.aws_s3_bucket.lake
}
