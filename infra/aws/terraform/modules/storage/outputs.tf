output "bucket_name" {
  description = "Name of the lake bucket."
  value       = aws_s3_bucket.lake.bucket
}

output "bucket_arn" {
  description = "ARN of the lake bucket."
  value       = aws_s3_bucket.lake.arn
}
