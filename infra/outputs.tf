output "ecr_repository_url" {
  description = "ECR repository URL"
  value       = aws_ecr_repository.main.repository_url
}

output "ecr_registry" {
  description = "ECR registry URL (without repository name)"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

output "ec2_public_ip" {
  description = "EC2 Elastic IP address"
  value       = aws_eip.main.public_ip
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.main.id
}

output "ssm_command" {
  description = "SSM command to connect to the instance"
  value       = "aws ssm start-session --target ${aws_instance.main.id} --profile donkey"
}

output "api_url" {
  description = "API endpoint URL (port 8000)"
  value       = "http://${var.domain_name}:8000"
}

output "domain_name" {
  description = "Primary domain"
  value       = var.domain_name
}

output "route53_nameservers" {
  description = "Route 53 nameservers - set these at your domain registrar for donkey.ai.kr"
  value       = aws_route53_zone.main.name_servers
}

output "s3_logs_bucket" {
  description = "S3 bucket for job logs"
  value       = aws_s3_bucket.logs.bucket
}

output "github_secrets" {
  description = "Values to set as GitHub Secrets"
  value = {
    ECR_REGISTRY   = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    S3_LOGS_BUCKET = aws_s3_bucket.logs.bucket
  }
}
