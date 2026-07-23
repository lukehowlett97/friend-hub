variable "project_name" {
  description = "Project name used for Hetzner resource names and labels."
  type        = string
  default     = "friend-hub"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "prod"
}

variable "server_type" {
  description = "Hetzner Cloud server type."
  type        = string
  default     = "cax11"
}

variable "location" {
  description = "Hetzner Cloud location, such as hel1, fsn1, nbg1, or ash."
  type        = string
  default     = "nbg1"
}

variable "domain_name" {
  description = "Fully-qualified domain name Caddy will serve."
  type        = string
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key authorized for root and deploy users."
  type        = string
}

variable "allowed_ssh_ips" {
  description = "CIDR ranges allowed to connect to SSH."
  type        = list(string)
}

variable "hcloud_token" {
  description = "Hetzner Cloud API token."
  type        = string
  sensitive   = true
}

variable "deploy_user" {
  description = "Non-root user that owns and runs the deployment."
  type        = string
  default     = "deploy"
}
