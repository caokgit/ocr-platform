variable "name" {
  description = "Name prefix; the key's alias becomes alias/<name>."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,40}$", var.name))
    error_message = "name: 3 to 41 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "deletion_window_in_days" {
  description = "Days a scheduled key deletion waits before the key is gone."
  type        = number
  default     = 30

  validation {
    condition     = var.deletion_window_in_days >= 7 && var.deletion_window_in_days <= 30
    error_message = "deletion_window_in_days: AWS allows 7 to 30."
  }
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
