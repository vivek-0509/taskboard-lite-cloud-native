# Terraform: cloud infrastructure for TaskBoard Lite

**Student:** Vivek Singh Solanki | **Roll number:** 24bcs10338

This module mirrors **session 19 (cloud-terraform)**: the same VPC -> public
subnet -> internet gateway -> route table -> security group -> EC2 -> S3
chain, with two changes that make it the capstone's "cloud" track:

| Session 19 | Session 21 (this module) |
|---|---|
| VPC `10.20.0.0/16` | VPC `10.30.0.0/16` (so both stacks can exist side by side) |
| EC2 runs nginx with a static page | EC2 installs Docker and runs the `taskboard-lite` image from GHCR |
| S3 bucket for assets | Private S3 bucket for database backups (versioning + SSE, public access blocked) |

Everything is created in one `apply` and removed in one `destroy`.

## Files

| File | Purpose |
|---|---|
| `versions.tf` | Terraform >= 1.6, AWS provider `~> 6.0`, provider region and default tags |
| `variables.tf` | Inputs with sensible defaults; only `bucket_name` is required |
| `main.tf` | Networking, security group, AL2023 AMI lookup (SSM), EC2 with Docker `user_data`, S3 bucket |
| `outputs.tf` | IDs, public IP, app URL, bucket name |
| `terraform.tfvars.example` | Template for your own `terraform.tfvars` |

## Prerequisites

- AWS CLI configured (`aws sts get-caller-identity` works)
- Terraform >= 1.6 (`brew install terraform`)
- The image `ghcr.io/vivek-0509/taskboard-lite:latest` must be **public** on
  GHCR (package settings -> change visibility) or the instance cannot pull it.
  It must be a `linux/amd64` image: the CI pipeline builds that; an image built
  on Apple Silicon is `linux/arm64` and will not start on `t3.micro`.

## Run

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit bucket_name at least

terraform init          # downloads the AWS provider, creates .terraform.lock.hcl
terraform fmt -check    # formatting
terraform validate      # syntax and references
terraform plan          # shows the ~14 resources that will be created
terraform apply         # type "yes"

# The first boot takes 1-2 minutes (dnf update + docker pull).
curl "$(terraform output -raw health_url)"
curl "$(terraform output -raw app_url)/api/config"
open  "$(terraform output -raw app_url)"
```

Clean up when done (the bucket uses `force_destroy = true`, so objects are
removed as well):

```bash
terraform destroy
```

## How the application gets onto the instance

`aws_instance.app` passes a `user_data` script that runs once on first boot:

1. `dnf install docker` and start the daemon.
2. Create `/opt/taskboard/data` and `chown 10001:10001` it. The container runs
   as the non-root user `app` (uid 10001), so the bind mount must be writable
   by that uid, otherwise `/ready` returns 503.
3. `docker run -d --restart unless-stopped -p 80:8000 -v /opt/taskboard/data:/app/data <image>`.

Changing `app_image` and running `apply` again replaces the instance
(`user_data_replace_on_change = true`), which is the simplest form of
"immutable infrastructure" rollout.

## Security notes

- The security group allows 80 from anywhere and 22 only from `allowed_ssh_cidr`.
- The S3 bucket blocks all public access, has versioning and SSE enabled.
- IMDSv2 is enforced (`http_tokens = "required"`); the root volume is encrypted.
- `DB_PASSWORD` is deliberately **not** put in `user_data` (it is readable from
  the instance metadata). A production setup reads it from SSM Parameter Store
  or Secrets Manager through an IAM instance profile.

## Cost

`t3.micro` + 8 GiB gp3 + an almost empty S3 bucket stays within the free tier
for a new account; remember to `terraform destroy` after taking screenshots.
