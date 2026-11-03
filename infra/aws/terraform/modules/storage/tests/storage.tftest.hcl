mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::ocr-platform-dev-lake" }
  }
}

variables {
  bucket_name = "ocr-platform-dev-lake"
  kms_key_arn = "arn:aws:kms:ap-southeast-1:123456789012:key/00000000-0000-0000-0000-000000000000"
}

run "private_versioned_encrypted_tls_only" {
  command = apply

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.lake.block_public_acls,
      aws_s3_bucket_public_access_block.lake.block_public_policy,
      aws_s3_bucket_public_access_block.lake.ignore_public_acls,
      aws_s3_bucket_public_access_block.lake.restrict_public_buckets,
    ])
    error_message = "All four public access blocks must be on."
  }

  assert {
    condition     = one(aws_s3_bucket_versioning.lake.versioning_configuration).status == "Enabled"
    error_message = "Versioning must be on: it is the undo for a bad write."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.lake.rule).apply_server_side_encryption_by_default).kms_master_key_id == var.kms_key_arn
    error_message = "Objects are encrypted with the platform key."
  }

  assert {
    condition     = jsondecode(aws_s3_bucket_policy.lake.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    error_message = "The bucket policy denies requests without TLS."
  }

  assert {
    condition     = !aws_s3_bucket.lake.force_destroy
    error_message = "A non-empty bucket survives destroy by default."
  }
}

run "uppercase_bucket_name_is_rejected" {
  command = plan

  variables {
    bucket_name = "OCR-Lake"
  }

  expect_failures = [var.bucket_name]
}
