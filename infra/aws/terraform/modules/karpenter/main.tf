data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_partition" "current" {}

locals {
  partition = data.aws_partition.current.partition
  region    = data.aws_region.current.region
  account   = data.aws_caller_identity.current.account_id

  # The four events that warn of a node going away; Karpenter drains the node before it does.
  interruption_events = {
    spot-interruption     = { source = ["aws.ec2"], detail_type = ["EC2 Spot Instance Interruption Warning"] }
    rebalance             = { source = ["aws.ec2"], detail_type = ["EC2 Instance Rebalance Recommendation"] }
    instance-state-change = { source = ["aws.ec2"], detail_type = ["EC2 Instance State-change Notification"] }
    scheduled-change      = { source = ["aws.health"], detail_type = ["AWS Health Event"] }
  }

  # Karpenter tags everything it creates; its permissions to change or delete are scoped by those tags.
  owned_request = {
    "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned"
    "aws:RequestTag/eks:eks-cluster-name"                      = var.cluster_name
  }
  owned_resource = {
    "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned"
  }
}

resource "aws_sqs_queue" "interruption" {
  name                      = "${var.cluster_name}-karpenter-interruption"
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true

  tags = var.tags
}

resource "aws_sqs_queue_policy" "interruption" {
  queue_url = aws_sqs_queue.interruption.url
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EventBridgeSends"
        Effect    = "Allow"
        Principal = { Service = ["events.amazonaws.com", "sqs.amazonaws.com"] }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.interruption.arn
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "sqs:*"
        Resource  = aws_sqs_queue.interruption.arn
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
}

resource "aws_cloudwatch_event_rule" "interruption" {
  for_each = local.interruption_events

  name        = "${var.cluster_name}-karpenter-${each.key}"
  description = "To Karpenter: ${each.value.detail_type[0]}"
  event_pattern = jsonencode({
    source        = each.value.source
    "detail-type" = each.value.detail_type
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "interruption" {
  for_each = local.interruption_events

  rule = aws_cloudwatch_event_rule.interruption[each.key].name
  arn  = aws_sqs_queue.interruption.arn
}

# The role every node Karpenter launches runs as.
resource "aws_iam_role" "node" {
  name = "${var.cluster_name}-karpenter-node"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryPullOnly",
    "AmazonSSMManagedInstanceCore",
  ])

  role       = aws_iam_role.node.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/${each.value}"
}

# The controller's role, assumed through Pod Identity by the karpenter service account.
resource "aws_iam_role" "controller" {
  name = "${var.cluster_name}-karpenter-controller"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "controller" {
  name = "karpenter-controller"
  role = aws_iam_role.controller.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LaunchFromSharedResources"
        Effect = "Allow"
        Action = ["ec2:RunInstances", "ec2:CreateFleet"]
        Resource = [
          "arn:${local.partition}:ec2:${local.region}::image/*",
          "arn:${local.partition}:ec2:${local.region}::snapshot/*",
          "arn:${local.partition}:ec2:${local.region}:*:security-group/*",
          "arn:${local.partition}:ec2:${local.region}:*:subnet/*",
          "arn:${local.partition}:ec2:${local.region}:*:capacity-reservation/*",
        ]
      },
      {
        Sid      = "LaunchFromOwnTemplates"
        Effect   = "Allow"
        Action   = ["ec2:RunInstances", "ec2:CreateFleet"]
        Resource = "arn:${local.partition}:ec2:${local.region}:*:launch-template/*"
        Condition = {
          StringEquals = local.owned_resource
          StringLike   = { "aws:ResourceTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid    = "CreateTaggedResources"
        Effect = "Allow"
        Action = ["ec2:RunInstances", "ec2:CreateFleet", "ec2:CreateLaunchTemplate"]
        Resource = [
          "arn:${local.partition}:ec2:${local.region}:*:fleet/*",
          "arn:${local.partition}:ec2:${local.region}:*:instance/*",
          "arn:${local.partition}:ec2:${local.region}:*:volume/*",
          "arn:${local.partition}:ec2:${local.region}:*:network-interface/*",
          "arn:${local.partition}:ec2:${local.region}:*:launch-template/*",
          "arn:${local.partition}:ec2:${local.region}:*:spot-instances-request/*",
        ]
        Condition = {
          StringEquals = local.owned_request
          StringLike   = { "aws:RequestTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid    = "TagOnCreate"
        Effect = "Allow"
        Action = "ec2:CreateTags"
        Resource = [
          "arn:${local.partition}:ec2:${local.region}:*:fleet/*",
          "arn:${local.partition}:ec2:${local.region}:*:instance/*",
          "arn:${local.partition}:ec2:${local.region}:*:volume/*",
          "arn:${local.partition}:ec2:${local.region}:*:network-interface/*",
          "arn:${local.partition}:ec2:${local.region}:*:launch-template/*",
          "arn:${local.partition}:ec2:${local.region}:*:spot-instances-request/*",
        ]
        Condition = {
          StringEquals = merge(local.owned_request, { "ec2:CreateAction" = ["RunInstances", "CreateFleet", "CreateLaunchTemplate"] })
          StringLike   = { "aws:RequestTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid      = "TerminateOwnNodes"
        Effect   = "Allow"
        Action   = ["ec2:TerminateInstances", "ec2:DeleteLaunchTemplate"]
        Resource = ["arn:${local.partition}:ec2:${local.region}:*:instance/*", "arn:${local.partition}:ec2:${local.region}:*:launch-template/*"]
        Condition = {
          StringEquals = local.owned_resource
          StringLike   = { "aws:ResourceTag/karpenter.sh/nodepool" = "*" }
        }
      },
      {
        Sid    = "ReadEc2InRegion"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones", "ec2:DescribeCapacityReservations", "ec2:DescribeImages",
          "ec2:DescribeInstances", "ec2:DescribeInstanceTypeOfferings", "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplates", "ec2:DescribeSecurityGroups", "ec2:DescribeSpotPriceHistory",
          "ec2:DescribeSubnets",
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = local.region } }
      },
      {
        Sid      = "ReadAmiParameters"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = "arn:${local.partition}:ssm:${local.region}::parameter/aws/service/*"
      },
      {
        Sid      = "ReadPrices"
        Effect   = "Allow"
        Action   = "pricing:GetProducts"
        Resource = "*"
      },
      {
        Sid      = "ReadInterruptionQueue"
        Effect   = "Allow"
        Action   = ["sqs:DeleteMessage", "sqs:GetQueueUrl", "sqs:ReceiveMessage"]
        Resource = aws_sqs_queue.interruption.arn
      },
      {
        Sid       = "PassNodeRole"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.node.arn
        Condition = { StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" } }
      },
      {
        Sid      = "ManageOwnInstanceProfiles"
        Effect   = "Allow"
        Action   = ["iam:CreateInstanceProfile", "iam:TagInstanceProfile", "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:DeleteInstanceProfile"]
        Resource = "arn:${local.partition}:iam::${local.account}:instance-profile/*"
        Condition = {
          StringEquals = merge(local.owned_resource, { "aws:ResourceTag/topology.kubernetes.io/region" = local.region })
        }
      },
      {
        Sid      = "CreateOwnInstanceProfiles"
        Effect   = "Allow"
        Action   = ["iam:CreateInstanceProfile", "iam:TagInstanceProfile"]
        Resource = "arn:${local.partition}:iam::${local.account}:instance-profile/*"
        Condition = {
          StringEquals = merge(local.owned_request, { "aws:RequestTag/topology.kubernetes.io/region" = local.region })
        }
      },
      {
        Sid      = "ReadInstanceProfiles"
        Effect   = "Allow"
        Action   = ["iam:GetInstanceProfile", "iam:ListInstanceProfiles"]
        Resource = "*"
      },
      {
        Sid      = "DiscoverApiEndpoint"
        Effect   = "Allow"
        Action   = "eks:DescribeCluster"
        Resource = "arn:${local.partition}:eks:${local.region}:${local.account}:cluster/${var.cluster_name}"
      },
    ]
  })
}

# Off when there is no cluster to bind to (the LocalStack run, which has no EKS).
resource "aws_eks_access_entry" "node" {
  count = var.bind_to_cluster ? 1 : 0

  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.node.arn
  type          = "EC2_LINUX"

  tags = var.tags
}

resource "aws_eks_pod_identity_association" "controller" {
  count = var.bind_to_cluster ? 1 : 0

  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = var.service_account
  role_arn        = aws_iam_role.controller.arn

  tags = var.tags
}
