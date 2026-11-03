output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "Address range of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs, one per AZ, in AZ order."
  value       = [for az in var.azs : aws_subnet.this["public-${az}"].id]
}

output "private_subnet_ids" {
  description = "Private subnet IDs, one per AZ, in AZ order; nodes and pods live here."
  value       = [for az in var.azs : aws_subnet.this["private-${az}"].id]
}

output "database_subnet_ids" {
  description = "Database subnet IDs, one per AZ, with no internet route."
  value       = [for az in var.azs : aws_subnet.this["database-${az}"].id]
}

output "nat_public_ips" {
  description = "Public addresses the private subnets reach the internet from."
  value       = [for eip in aws_eip.nat : eip.public_ip]
}
