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
}

variables {
  name = "ocr-platform-dev"
}

run "key_rotates_and_logs_may_use_it" {
  command = apply

  assert {
    condition     = aws_kms_key.this.enable_key_rotation
    error_message = "Key rotation must be on."
  }

  assert {
    condition     = aws_kms_alias.this.name == "alias/ocr-platform-dev"
    error_message = "The alias follows the name."
  }

  assert {
    condition = contains(
      [for s in jsondecode(aws_kms_key.this.policy).Statement : s.Principal],
      { Service = "logs.ap-southeast-1.amazonaws.com" }
    )
    error_message = "CloudWatch Logs in the key's region must be allowed in the key policy."
  }
}

run "deletion_window_out_of_range_is_rejected" {
  command = plan

  variables {
    deletion_window_in_days = 3
  }

  expect_failures = [var.deletion_window_in_days]
}
