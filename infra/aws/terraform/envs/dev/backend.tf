# State in S3, locked by a lock file next to it (Terraform 1.10+), no DynamoDB table.
# The bucket is created once by hand or by a bootstrap stack; `terraform init -backend=false` skips it for checks.
terraform {
  backend "s3" {
    bucket       = "ocr-platform-tfstate-dev"
    key          = "ocr-platform/dev/terraform.tfstate"
    region       = "ap-southeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
