mock_provider "aws" {}

variables {
  name                   = "ocr-platform-dev"
  vpc_id                 = "vpc-0123456789abcdef0"
  subnet_ids             = ["subnet-0000000000000000a", "subnet-0000000000000000b", "subnet-0000000000000000c"]
  client_security_groups = { eks-cluster = "sg-0123456789abcdef0" }
  kms_key_arn            = "arn:aws:kms:ap-southeast-1:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "private_encrypted_protected_and_ready_for_cdc" {
  command = apply

  assert {
    condition     = !aws_db_instance.this.publicly_accessible && aws_db_instance.this.storage_encrypted
    error_message = "The database is private and encrypted."
  }

  assert {
    condition     = aws_db_instance.this.deletion_protection && aws_db_instance.this.manage_master_user_password
    error_message = "Deletion protection on, password managed by RDS."
  }

  assert {
    condition     = [for p in aws_db_parameter_group.this.parameter : p.value if p.name == "rds.logical_replication"] == ["1"]
    error_message = "Logical replication must be on for CDC and low-downtime upgrades."
  }

  assert {
    condition     = aws_db_parameter_group.this.family == "postgres17"
    error_message = "The parameter group follows the major version."
  }

  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.from_clients) == 1
    error_message = "One ingress rule per client security group, none from addresses."
  }
}

run "no_backups_is_rejected" {
  command = plan

  variables {
    backup_retention_days = 0
  }

  expect_failures = [var.backup_retention_days]
}

run "one_subnet_is_rejected" {
  command = plan

  variables {
    subnet_ids = ["subnet-0000000000000000a"]
  }

  expect_failures = [var.subnet_ids]
}
