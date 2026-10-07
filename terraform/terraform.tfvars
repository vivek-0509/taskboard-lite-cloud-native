# Copy to terraform.tfvars and adjust. terraform.tfvars is git-ignored.
aws_region         = "us-east-1"
project_name       = "taskboard-lite"
vpc_cidr           = "10.30.0.0/16"
public_subnet_cidr = "10.30.1.0/24"
instance_type      = "t3.micro"

# Must be globally unique, lowercase, 3-63 characters.
bucket_name = "vivek-taskboard-backups-20261007-cb9919"

# Restrict SSH to your own public IP (curl ifconfig.me).
allowed_ssh_cidr = "0.0.0.0/0"
# Existing EC2 key pair name, or "" for no SSH key.
key_name = ""

# Image published by .github/workflows/final-pipeline.yml (linux/amd64).
app_image = "ghcr.io/vivek-0509/taskboard-lite:latest"
app_env   = "production"
