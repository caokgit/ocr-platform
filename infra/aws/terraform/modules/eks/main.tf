data "aws_partition" "current" {}

locals {
  managed_policy = "arn:${data.aws_partition.current.partition}:iam::aws:policy"

  pod_identity_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  # coredns needs nodes to schedule on, so it waits for the node group; the rest install with the cluster.
  addons = {
    vpc-cni                = { before_nodes = true }
    kube-proxy             = { before_nodes = true }
    eks-pod-identity-agent = { before_nodes = true }
    coredns                = { before_nodes = false }
    aws-ebs-csi-driver     = { before_nodes = false }
  }
}

resource "aws_iam_role" "cluster" {
  name = "${var.name}-cluster"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "${local.managed_policy}/AmazonEKSClusterPolicy"
}

resource "aws_cloudwatch_log_group" "cluster" {
  # EKS writes control plane logs to this exact name; creating it first sets retention and encryption.
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = length(var.public_access_cidrs) > 0
    public_access_cidrs     = length(var.public_access_cidrs) > 0 ? var.public_access_cidrs : null
  }

  # Access entries (IAM principals mapped to cluster policies) replace the aws-auth ConfigMap.
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }

  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = var.kms_key_arn
    }
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator"]

  upgrade_policy {
    support_type = "STANDARD"
  }

  tags = var.tags

  depends_on = [aws_iam_role_policy_attachment.cluster, aws_cloudwatch_log_group.cluster]
}

# Karpenter finds the security group its nodes join by this tag.
resource "aws_ec2_tag" "cluster_sg_discovery" {
  resource_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  key         = "karpenter.sh/discovery"
  value       = var.name
}

resource "aws_eks_access_entry" "admin" {
  for_each = toset(var.admin_principal_arns)

  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
}

resource "aws_eks_access_policy_association" "admin" {
  for_each = toset(var.admin_principal_arns)

  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.admin]
}

# The system node group: on-demand, never spot, for the pods that run the cluster (CoreDNS, Karpenter, Argo CD).
resource "aws_iam_role" "system_nodes" {
  name = "${var.name}-system-nodes"
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

resource "aws_iam_role_policy_attachment" "system_nodes" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryPullOnly",
    "AmazonSSMManagedInstanceCore",
  ])

  role       = aws_iam_role.system_nodes.name
  policy_arn = "${local.managed_policy}/${each.value}"
}

resource "aws_eks_node_group" "system" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "system"
  node_role_arn   = aws_iam_role.system_nodes.arn
  subnet_ids      = var.subnet_ids
  capacity_type   = "ON_DEMAND"
  instance_types  = var.system_instance_types
  ami_type        = "AL2023_x86_64_STANDARD"

  scaling_config {
    min_size     = var.system_node_count
    desired_size = var.system_node_count
    max_size     = var.system_node_count + 1
  }

  update_config {
    max_unavailable = 1
  }

  labels = { "node-role" = "system" }

  tags = var.tags

  depends_on = [aws_iam_role_policy_attachment.system_nodes, aws_eks_addon.before_nodes]

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.name}-ebs-csi"
  assume_role_policy = local.pod_identity_trust

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "${local.managed_policy}/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_addon" "before_nodes" {
  for_each = { for k, v in local.addons : k => v if v.before_nodes }

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  tags = var.tags
}

resource "aws_eks_addon" "after_nodes" {
  for_each = { for k, v in local.addons : k => v if !v.before_nodes }

  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  dynamic "pod_identity_association" {
    for_each = each.key == "aws-ebs-csi-driver" ? [1] : []
    content {
      role_arn        = aws_iam_role.ebs_csi.arn
      service_account = "ebs-csi-controller-sa"
    }
  }

  tags = var.tags

  depends_on = [aws_eks_node_group.system]
}

resource "aws_eks_pod_identity_association" "this" {
  for_each = var.pod_identities

  cluster_name    = aws_eks_cluster.this.name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = each.value.arn

  tags = var.tags

  depends_on = [aws_eks_addon.before_nodes]
}
