variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "donkey"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "domain_name" {
  description = "Primary domain (e.g. donkey.ai.kr)"
  type        = string
  default     = "donkey.ai.kr"
}

variable "rds_username" {
  description = "RDS MySQL master username"
  type        = string
  default     = "donkey"
}

