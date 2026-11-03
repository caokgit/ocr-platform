output "cluster_name" {
  description = "Name of the cluster."
  value       = aws_eks_cluster.this.name
}

output "cluster_arn" {
  description = "ARN of the cluster."
  value       = aws_eks_cluster.this.arn
}

output "endpoint" {
  description = "API server endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "certificate_authority_data" {
  description = "Base64 CA bundle for kubeconfig."
  value       = aws_eks_cluster.this.certificate_authority[0].data
}

output "cluster_security_group_id" {
  description = "Security group EKS created for the control plane and nodes."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}
