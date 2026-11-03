output "vpc_id" {
  description = "VPC created in LocalStack."
  value       = module.network.vpc_id
}

output "lake_bucket" {
  description = "Lake bucket."
  value       = module.storage.bucket_name
}

output "secret_name" {
  description = "Secret External Secrets reads."
  value       = aws_secretsmanager_secret.podinfo.name
}

output "work_queue_url" {
  description = "Queue the KEDA drill scales on."
  value       = aws_sqs_queue.work.url
}

output "karpenter_queue" {
  description = "Karpenter's interruption queue."
  value       = module.karpenter.queue_name
}

output "pg_backup_bucket" {
  description = "Bucket for CloudNativePG backups."
  value       = module.pg_backups.bucket_name
}
