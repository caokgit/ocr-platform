# Every call goes to LocalStack (infra/kind/localstack.sh starts it); the keys are LocalStack's fixed test keys.
provider "aws" {
  region                      = "ap-southeast-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  s3_use_path_style           = true

  endpoints {
    ec2            = var.endpoint
    events         = var.endpoint
    iam            = var.endpoint
    kms            = var.endpoint
    logs           = var.endpoint
    s3             = var.endpoint
    s3control      = var.endpoint
    secretsmanager = var.endpoint
    sqs            = var.endpoint
    sts            = var.endpoint
  }

  default_tags {
    tags = {
      project     = "ocr-platform"
      environment = "localstack"
      managed-by  = "terraform"
    }
  }
}
