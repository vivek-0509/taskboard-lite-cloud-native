variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "taskboard-lite"
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC."
  type        = string
  default     = "10.30.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block of the public subnet."
  type        = string
  default     = "10.30.1.0/24"
}

variable "instance_type" {
  description = "EC2 instance type (free-tier eligible, x86_64)."
  type        = string
  default     = "t3.micro"
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to SSH to the instance. Narrow this to your own IP (e.g. 203.0.113.4/32)."
  type        = string
  default     = "0.0.0.0/0"
}

variable "key_name" {
  description = "Name of an existing EC2 key pair for SSH access. Leave empty for no key."
  type        = string
  default     = ""
}

variable "app_image" {
  description = "Container image to run on the instance. Must be a linux/amd64 image (built by the CI pipeline)."
  type        = string
  default     = "ghcr.io/vivek-0509/taskboard-lite:latest"
}

variable "app_env" {
  description = "Value of APP_ENV passed to the container."
  type        = string
  default     = "production"
}

variable "bucket_name" {
  description = "Globally unique S3 bucket name used for backups of the task database."
  type        = string
}
