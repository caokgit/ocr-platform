# The whole design, applied against a mocked AWS: every module wired together, no account needed.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "ap-southeast-1" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:ap-southeast-1:123456789012:key/00000000-0000-0000-0000-000000000000" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/ocr-platform-dev-mock" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:ap-southeast-1:123456789012:log-group:/mock" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::ocr-platform-dev-lake-123456789012" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:ap-southeast-1:123456789012:ocr-platform-dev-karpenter-interruption"
      url = "https://sqs.ap-southeast-1.amazonaws.com/123456789012/ocr-platform-dev-karpenter-interruption"
    }
  }
  mock_resource "aws_eks_cluster" {
    defaults = {
      arn                   = "arn:aws:eks:ap-southeast-1:123456789012:cluster/ocr-platform-dev"
      vpc_config            = { cluster_security_group_id = "sg-0123456789abcdef0", vpc_id = "vpc-0123456789abcdef0" }
      certificate_authority = [{ data = "bW9jaw==" }]
    }
  }
}

run "the_whole_design_applies" {
  command = apply

  assert {
    condition     = output.lake_bucket == "ocr-platform-dev-lake-123456789012"
    error_message = "The lake bucket name carries the account ID, so it is globally unique."
  }

  assert {
    condition     = output.karpenter.interruption_queue == "ocr-platform-dev-karpenter-interruption"
    error_message = "Karpenter gets its interruption queue."
  }

  assert {
    condition     = length(output.nat_public_ips) == 1
    error_message = "Dev runs one NAT gateway."
  }
}

run "production_shape" {
  command = plan

  variables {
    single_nat_gateway = false
    database_multi_az  = true
  }

  assert {
    condition     = length(module.network.nat_public_ips) == 3
    error_message = "One NAT gateway per AZ."
  }
}
