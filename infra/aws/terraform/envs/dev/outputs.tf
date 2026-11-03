output "cluster_name" {
  description = "EKS cluster name, for `aws eks update-kubeconfig`."
  value       = module.eks.cluster_name
}

output "karpenter" {
  description = "What Karpenter's Helm values and EC2NodeClass need."
  value = {
    interruption_queue = module.karpenter.queue_name
    node_role          = module.karpenter.node_role_name
  }
}

output "lake_bucket" {
  description = "The lake bucket."
  value       = module.storage.bucket_name
}

output "database_endpoint" {
  description = "RDS endpoint."
  value       = module.database.endpoint
}

output "nat_public_ips" {
  description = "Egress addresses, for allowlists on the other side."
  value       = module.network.nat_public_ips
}
