output "queue_name" {
  description = "Interruption queue name, for Karpenter's settings.interruptionQueue."
  value       = aws_sqs_queue.interruption.name
}

output "queue_url" {
  description = "URL of the interruption queue."
  value       = aws_sqs_queue.interruption.url
}

output "node_role_name" {
  description = "Role for Karpenter's nodes, named in the EC2NodeClass."
  value       = aws_iam_role.node.name
}

output "controller_role_arn" {
  description = "Role of the Karpenter controller."
  value       = aws_iam_role.controller.arn
}
