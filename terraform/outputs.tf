output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_id" {
  description = "ID of the public subnet."
  value       = aws_subnet.public.id
}

output "security_group_id" {
  description = "ID of the web security group."
  value       = aws_security_group.web.id
}

output "ec2_instance_id" {
  description = "ID of the EC2 instance."
  value       = aws_instance.app.id
}

output "ec2_public_ip" {
  description = "Public IP of the application host."
  value       = aws_instance.app.public_ip
}

output "app_url" {
  description = "URL of the TaskBoard Lite UI."
  value       = "http://${aws_instance.app.public_ip}"
}

output "health_url" {
  description = "Liveness endpoint, handy for a quick curl after apply."
  value       = "http://${aws_instance.app.public_ip}/health"
}

output "ssh_command" {
  description = "SSH command (only works when key_name was set and allowed_ssh_cidr includes you)."
  value       = "ssh -i ~/.ssh/${var.key_name != "" ? var.key_name : "<key>"}.pem ec2-user@${aws_instance.app.public_ip}"
}

output "backup_bucket_name" {
  description = "Name of the private S3 backup bucket."
  value       = aws_s3_bucket.backups.bucket
}

output "ami_id" {
  description = "AMI used for the instance."
  value       = data.aws_ssm_parameter.al2023_ami.value
  sensitive   = true
}
