variable "cluster_name" {
  description = "EKS cluster Karpenter serves; names the queue, rules and roles."
  type        = string
}

variable "bind_to_cluster" {
  description = "Create the node access entry and the controller's Pod Identity association; false where no cluster exists."
  type        = bool
  default     = true
}

variable "namespace" {
  description = "Namespace Karpenter's controller runs in."
  type        = string
  default     = "kube-system"
}

variable "service_account" {
  description = "Service account of Karpenter's controller."
  type        = string
  default     = "karpenter"
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}
