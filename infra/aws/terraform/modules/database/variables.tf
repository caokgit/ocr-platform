variable "name" {
  description = "Identifier of the instance and prefix of its resources."
  type        = string
}

variable "vpc_id" {
  description = "VPC the database lives in."
  type        = string
}

variable "subnet_ids" {
  description = "Database subnets, at least two AZs."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "subnet_ids: RDS needs subnets in at least two AZs."
  }
}

variable "client_security_groups" {
  description = "Security groups allowed to connect on 5432, by a name known at plan time (for example eks-cluster)."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "KMS key for storage, the master password secret and Performance Insights."
  type        = string
}

variable "engine_major_version" {
  description = "PostgreSQL major version; minor versions upgrade automatically."
  type        = string
  default     = "17"

  validation {
    condition     = contains(["16", "17"], var.engine_major_version)
    error_message = "engine_major_version: 16 or 17."
  }
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"

  validation {
    condition     = startswith(var.instance_class, "db.")
    error_message = "instance_class: an RDS class, starting with db."
  }
}

variable "database_name" {
  description = "Name of the first database."
  type        = string
  default     = "platform"
}

variable "allocated_storage_gb" {
  description = "Starting storage in GiB."
  type        = number
  default     = 20
}

variable "max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling in GiB."
  type        = number
  default     = 100
}

variable "multi_az" {
  description = "A standby in a second AZ with automatic failover; doubles the instance cost."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Days of automated backups, also the point-in-time restore window."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 35
    error_message = "backup_retention_days: 1 to 35; 0 would turn backups and point-in-time restore off."
  }
}

variable "deletion_protection" {
  description = "Refuse to delete the instance until this is turned off."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
