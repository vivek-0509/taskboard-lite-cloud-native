# ------------------------------------------------------------------
# Networking: VPC -> Subnet -> Internet Gateway -> Route Table
# (same layout as session 19, different CIDR so both can coexist)
# ------------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = { Name = "${var.project_name}-public-subnet" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project_name}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ------------------------------------------------------------------
# Security Group: HTTP from anywhere, SSH from the allowed CIDR
# ------------------------------------------------------------------
resource "aws_security_group" "web" {
  name        = "${var.project_name}-web-sg"
  description = "Allow HTTP and SSH to the TaskBoard Lite host"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  egress {
    description = "All outbound (image pull from GHCR, dnf)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-web-sg" }
}

# ------------------------------------------------------------------
# Compute: latest Amazon Linux 2023 AMI + EC2 host running the container
# ------------------------------------------------------------------
data "aws_ssm_parameter" "al2023_ami" {
  # t3.micro is x86_64. For an arm64 instance (t4g.micro) switch to the
  # "...-arm64" parameter and build the image for linux/arm64.
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.web.id]
  associate_public_ip_address = true
  key_name                    = var.key_name != "" ? var.key_name : null

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  # Installs Docker and runs the image published by the CI pipeline.
  # DB_PASSWORD is intentionally not set here: user_data is readable from the
  # instance metadata, so a real secret would come from SSM Parameter Store /
  # Secrets Manager through an instance profile.
  user_data = <<-EOT
    #!/bin/bash
    set -euxo pipefail
    dnf update -y
    dnf install -y docker
    systemctl enable --now docker
    usermod -aG docker ec2-user

    # The container runs as uid 10001 (see docker/Dockerfile); the bind mount must be writable by it.
    mkdir -p /opt/taskboard/data
    chown 10001:10001 /opt/taskboard/data

    docker pull ${var.app_image}
    docker run -d --name taskboard --restart unless-stopped \
      -p 80:8000 \
      -e APP_ENV=${var.app_env} \
      -e LOG_LEVEL=INFO \
      -e FEATURE_FLAGS=dark-mode,metrics \
      -v /opt/taskboard/data:/app/data \
      ${var.app_image}
  EOT

  user_data_replace_on_change = true

  # Make sure the route to the internet exists before boot (user_data needs dnf and GHCR).
  depends_on = [aws_route_table_association.public]

  tags = { Name = "${var.project_name}-app" }
}

# ------------------------------------------------------------------
# Storage: private S3 bucket for database backups
# ------------------------------------------------------------------
resource "aws_s3_bucket" "backups" {
  bucket        = var.bucket_name
  force_destroy = true

  tags = { Name = var.bucket_name }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "instance_info" {
  bucket  = aws_s3_bucket.backups.id
  key     = "instance-info.txt"
  content = "EC2 ${aws_instance.app.id} public IP ${aws_instance.app.public_ip} runs ${var.app_image} in ${aws_subnet.public.id}\n"
}
