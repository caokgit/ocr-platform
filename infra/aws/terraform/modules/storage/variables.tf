variable "bucket_name" {
  description = "Globally unique name of the lake bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name: 3 to 63 lowercase letters, digits, dots or hyphens."
  }
}

variable "kms_key_arn" {
  description = "KMS key for server-side encryption."
  type        = string
}

variable "noncurrent_version_days" {
  description = "Days a replaced or deleted object version is kept, the window to undo a bad write."
  type        = number
  default     = 30
}

variable "bronze_ia_after_days" {
  description = "Days before raw (bronze) objects move to Infrequent Access."
  type        = number
  default     = 30

  validation {
    condition     = var.bronze_ia_after_days >= 30
    error_message = "bronze_ia_after_days: S3 needs at least 30 days before STANDARD_IA."
  }
}

variable "force_destroy" {
  description = "Let destroy delete a non-empty bucket; only for throwaway environments."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
