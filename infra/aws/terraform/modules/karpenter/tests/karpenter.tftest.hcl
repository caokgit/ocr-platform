mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/ocr-platform-dev-karpenter" }
  }
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:ap-southeast-1:123456789012:ocr-platform-dev-karpenter-interruption"
      url = "https://sqs.ap-southeast-1.amazonaws.com/123456789012/ocr-platform-dev-karpenter-interruption"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_region" {
    defaults = { region = "ap-southeast-1" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}

variables {
  cluster_name = "ocr-platform-dev"
}

run "four_events_feed_the_queue" {
  command = apply

  assert {
    condition     = length(aws_cloudwatch_event_rule.interruption) == 4 && length(aws_cloudwatch_event_target.interruption) == 4
    error_message = "Spot warning, rebalance, state change and health events each have a rule and a target."
  }

  assert {
    condition     = jsondecode(aws_cloudwatch_event_rule.interruption["spot-interruption"].event_pattern)["detail-type"] == ["EC2 Spot Instance Interruption Warning"]
    error_message = "The spot rule matches the two-minute warning."
  }

  assert {
    condition     = alltrue([for t in aws_cloudwatch_event_target.interruption : t.arn == aws_sqs_queue.interruption.arn])
    error_message = "Every rule targets the interruption queue."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.controller.policy).Statement :
      s.Sid != "TerminateOwnNodes" || s.Condition.StringEquals["aws:ResourceTag/kubernetes.io/cluster/ocr-platform-dev"] == "owned"
    ])
    error_message = "The controller may terminate only instances tagged as this cluster's."
  }

  assert {
    condition     = length(aws_eks_access_entry.node) == 1 && aws_eks_access_entry.node[0].type == "EC2_LINUX"
    error_message = "Karpenter's nodes may join the cluster."
  }
}

run "no_cluster_no_bindings" {
  command = plan

  variables {
    bind_to_cluster = false
  }

  assert {
    condition     = length(aws_eks_access_entry.node) == 0 && length(aws_eks_pod_identity_association.controller) == 0
    error_message = "Without a cluster, only the queue, rules and roles are created."
  }
}
