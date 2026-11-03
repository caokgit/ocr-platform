variable "name" {
  description = "Name prefix for every resource, also the Karpenter discovery tag value."
  type        = string
}

variable "region" {
  description = "AWS region, for the S3 endpoint's service name."
  type        = string
}

variable "cidr" {
  description = "The VPC's address range; a /16 leaves room for three tiers of /20 subnets in up to four AZs."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(cidrhost(var.cidr, 0)) && tonumber(split("/", var.cidr)[1]) == 16
    error_message = "cidr: a valid IPv4 /16."
  }
}

variable "azs" {
  description = "Availability zones, one subnet per tier in each."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2 && length(var.azs) <= 4 && length(distinct(var.azs)) == length(var.azs)
    error_message = "azs: 2 to 4 distinct zones."
  }
}

variable "single_nat_gateway" {
  description = "One NAT gateway for all AZs (cheaper, one AZ's failure cuts egress) or one per AZ."
  type        = bool
  default     = true
}

variable "flow_logs_retention_days" {
  description = "Days to keep rejected-traffic flow logs; 0 turns flow logs off."
  type        = number
  default     = 14
}

variable "kms_key_arn" {
  description = "KMS key that encrypts the flow logs; null uses CloudWatch's default encryption."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
