# The provider still validates ARN formats under a mock, so resources whose ARN is passed on get a realistic one.
mock_provider "aws" {
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:ap-southeast-1:123456789012:log-group:/vpc/ocr-platform-dev/flow-logs" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/ocr-platform-dev-vpc-flow-logs" }
  }
}

variables {
  name   = "ocr-platform-dev"
  region = "ap-southeast-1"
  azs    = ["ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c"]
}

run "three_tiers_in_three_azs_with_one_nat" {
  command = apply

  assert {
    condition     = length(aws_subnet.this) == 9
    error_message = "Three tiers in three AZs make nine subnets."
  }

  assert {
    condition     = aws_subnet.this["private-ap-southeast-1b"].cidr_block == "10.40.x.x/20" && aws_subnet.this["database-ap-southeast-1c"].cidr_block == "10.40.x.x/20"
    error_message = "Subnet ranges follow block 4 x tier + AZ index."
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 1
    error_message = "single_nat_gateway gives one NAT gateway."
  }

  assert {
    condition     = alltrue([for rt in aws_route_table.private : one(rt.route).nat_gateway_id == aws_nat_gateway.this["ap-southeast-1a"].id])
    error_message = "Every private route table points at the one NAT gateway."
  }

  assert {
    condition     = length(aws_route_table.database.route) == 0
    error_message = "Database subnets have no route out."
  }

  assert {
    condition     = aws_subnet.this["private-ap-southeast-1a"].tags["karpenter.sh/discovery"] == "ocr-platform-dev"
    error_message = "Private subnets carry the Karpenter discovery tag."
  }
}

run "one_nat_per_az" {
  command = plan

  variables {
    single_nat_gateway = false
  }

  assert {
    condition     = length(aws_nat_gateway.this) == 3
    error_message = "Without single_nat_gateway, each AZ gets its own NAT gateway."
  }
}

run "flow_logs_off" {
  command = plan

  variables {
    flow_logs_retention_days = 0
  }

  assert {
    condition     = length(aws_flow_log.this) == 0
    error_message = "Retention 0 turns flow logs off."
  }
}

run "not_a_slash_16_is_rejected" {
  command = plan

  variables {
    cidr = "10.40.0.0/20"
  }

  expect_failures = [var.cidr]
}

run "one_az_is_rejected" {
  command = plan

  variables {
    azs = ["ap-southeast-1a"]
  }

  expect_failures = [var.azs]
}
