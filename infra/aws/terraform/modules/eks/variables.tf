variable "name" {
  description = "Cluster name, also the Karpenter discovery tag value."
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes minor version."
  type        = string
  default     = "1.35"

  validation {
    condition     = can(regex("^1\\.[0-9]{2}$", var.kubernetes_version))
    error_message = "kubernetes_version: a minor version such as 1.35."
  }
}

variable "subnet_ids" {
  description = "Private subnets for the control plane's network interfaces and the system nodes."
  type        = list(string)
}

variable "public_access_cidrs" {
  description = "Addresses allowed to reach the API endpoint from the internet; empty makes the endpoint private only."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.public_access_cidrs, "0.0.0.0/0")
    error_message = "public_access_cidrs: the API endpoint is never open to the whole internet."
  }
}

variable "admin_principal_arns" {
  description = "IAM roles or users given cluster admin through access entries."
  type        = list(string)
  default     = []
}

variable "system_instance_types" {
  description = "Instance types for the on-demand system node group."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "system_node_count" {
  description = "Nodes in the system node group, at least two for CoreDNS and Karpenter to survive one node."
  type        = number
  default     = 2

  validation {
    condition     = var.system_node_count >= 2
    error_message = "system_node_count: at least 2."
  }
}

variable "pod_identities" {
  description = "Pod Identity associations: role ARN, namespace and service account (the iam module's roles output)."
  type = map(object({
    arn             = string
    namespace       = string
    service_account = string
  }))
  default = {}
}

variable "kms_key_arn" {
  description = "KMS key for Kubernetes secrets envelope encryption and the control plane log group."
  type        = string
}

variable "log_retention_days" {
  description = "Days to keep control plane logs."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
