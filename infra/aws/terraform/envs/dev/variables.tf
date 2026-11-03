variable "region" {
  description = "AWS region."
  type        = string
  default     = "ap-southeast-1"
}

variable "environment" {
  description = "Environment name, part of every resource name."
  type        = string
  default     = "dev"
}

variable "single_nat_gateway" {
  description = "One NAT gateway for the VPC (dev) or one per AZ (production)."
  type        = bool
  default     = true
}

variable "database_multi_az" {
  description = "RDS standby in a second AZ."
  type        = bool
  default     = false
}

variable "api_allowed_cidrs" {
  description = "Addresses allowed to reach the EKS API from the internet; empty (the default) keeps the API private, reached over the VPN."
  type        = list(string)
  default     = []
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone cert-manager writes DNS-01 challenge records in."
  type        = string
  default     = "Z0000000000000000000"
}

variable "admin_principal_arns" {
  description = "IAM roles given cluster admin (for example the SSO platform-admin role)."
  type        = list(string)
  default     = []
}
