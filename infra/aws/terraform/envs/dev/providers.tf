provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = "ocr-platform"
      environment = var.environment
      managed-by  = "terraform"
    }
  }
}
