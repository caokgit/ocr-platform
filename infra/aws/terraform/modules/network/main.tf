locals {
  tiers = {
    public   = 0
    private  = 1
    database = 2
  }

  # One /20 per tier per AZ out of the /16: tier t, AZ i gets block 4t + i (blocks 3, 7, 11 and up stay free).
  subnets = merge([
    for tier, t in local.tiers : {
      for i, az in var.azs : "${tier}-${az}" => {
        tier = tier
        az   = az
        cidr = cidrsubnet(var.cidr, 4, 4 * t + i)
      }
    }
  ]...)

  nat_azs = var.single_nat_gateway ? [var.azs[0]] : var.azs

  # Kubernetes and Karpenter find subnets by tag, not by ID.
  tier_tags = {
    public   = { "kubernetes.io/role/elb" = "1" }
    private  = { "kubernetes.io/role/internal-elb" = "1", "karpenter.sh/discovery" = var.name }
    database = {}
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, { Name = var.name })
}

# The default security group allows all traffic between its members; nothing should use it, so it is emptied.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-default-unused" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = var.name })
}

resource "aws_subnet" "this" {
  for_each = local.subnets

  vpc_id            = aws_vpc.this.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az

  tags = merge(var.tags, local.tier_tags[each.value.tier], {
    Name = "${var.name}-${each.key}"
    tier = each.value.tier
  })
}

resource "aws_eip" "nat" {
  for_each = toset(local.nat_azs)

  domain = "vpc"

  tags = merge(var.tags, { Name = "${var.name}-nat-${each.key}" })
}

resource "aws_nat_gateway" "this" {
  for_each = toset(local.nat_azs)

  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.this["public-${each.key}"].id

  tags = merge(var.tags, { Name = "${var.name}-${each.key}" })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(var.tags, { Name = "${var.name}-public" })
}

# One private route table per AZ, so moving from one NAT to one per AZ changes routes, not tables.
resource "aws_route_table" "private" {
  for_each = toset(var.azs)

  vpc_id = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[var.single_nat_gateway ? var.azs[0] : each.key].id
  }

  tags = merge(var.tags, { Name = "${var.name}-private-${each.key}" })
}

# Database subnets have no route to the internet at all.
resource "aws_route_table" "database" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name}-database" })
}

resource "aws_route_table_association" "this" {
  for_each = local.subnets

  subnet_id = aws_subnet.this[each.key].id
  route_table_id = (
    each.value.tier == "public" ? aws_route_table.public.id :
    each.value.tier == "private" ? aws_route_table.private[each.value.az].id :
    aws_route_table.database.id
  )
}

# S3 traffic from private subnets goes through a free gateway endpoint instead of the NAT, which bills per GB.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat([for rt in aws_route_table.private : rt.id], [aws_route_table.database.id])

  tags = merge(var.tags, { Name = "${var.name}-s3" })
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.flow_logs_retention_days > 0 ? 1 : 0

  name              = "/vpc/${var.name}/flow-logs"
  retention_in_days = var.flow_logs_retention_days
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_iam_role" "flow_logs" {
  count = var.flow_logs_retention_days > 0 ? 1 : 0

  name = "${var.name}-vpc-flow-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "flow_logs" {
  count = var.flow_logs_retention_days > 0 ? 1 : 0

  name = "write-flow-logs"
  role = aws_iam_role.flow_logs[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.flow_logs[0].arn}:*"
    }]
  })
}

resource "aws_flow_log" "this" {
  count = var.flow_logs_retention_days > 0 ? 1 : 0

  vpc_id          = aws_vpc.this.id
  traffic_type    = "REJECT"
  log_destination = aws_cloudwatch_log_group.flow_logs[0].arn
  iam_role_arn    = aws_iam_role.flow_logs[0].arn

  tags = var.tags
}
