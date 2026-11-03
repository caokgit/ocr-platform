output "endpoint" {
  description = "Host and port to connect to."
  value       = aws_db_instance.this.endpoint
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret holding the master password, managed by RDS."
  value       = one(aws_db_instance.this.master_user_secret[*].secret_arn)
}

output "security_group_id" {
  description = "Security group of the database."
  value       = aws_security_group.this.id
}
