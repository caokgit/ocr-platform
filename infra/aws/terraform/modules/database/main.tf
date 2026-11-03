resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids

  tags = var.tags
}

resource "aws_security_group" "this" {
  name        = "${var.name}-postgres"
  description = "Postgres from the cluster only"
  vpc_id      = var.vpc_id

  tags = var.tags
}

# Keyed by a name known at plan time: the security group IDs often are not (the cluster's is created in the same run).
resource "aws_vpc_security_group_ingress_rule" "from_clients" {
  for_each = var.client_security_groups

  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "Postgres from ${each.key}"
}

# Logical replication is what CDC (Debezium) and a low-downtime major upgrade both need.
resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-pg${var.engine_major_version}"
  family = "postgres${var.engine_major_version}"

  parameter {
    name         = "rds.logical_replication"
    value        = "1"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  # A query waiting on a lock gives up after 30 s instead of holding a worker until the app times out.
  parameter {
    name  = "lock_timeout"
    value = "30000"
  }

  tags = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = var.engine_major_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_name  = var.database_name
  username = "platform_admin"
  # RDS creates the password, keeps it in Secrets Manager and rotates it; it never passes through Terraform state.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.kms_key_arn

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period   = var.backup_retention_days
  backup_window             = "18:00-19:00" # UTC; 01:00-02:00 UTC+7
  maintenance_window        = "sun:19:30-sun:20:30"
  copy_tags_to_snapshot     = true
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"

  auto_minor_version_upgrade          = true
  iam_database_authentication_enabled = true
  performance_insights_enabled        = true
  performance_insights_kms_key_id     = var.kms_key_arn
  enabled_cloudwatch_logs_exports     = ["postgresql", "upgrade"]

  tags = var.tags
}
