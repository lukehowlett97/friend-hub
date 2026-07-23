output "server_ipv4" {
  description = "Public IPv4 address of the Friend-Hub VPS."
  value       = hcloud_server.friend_hub.ipv4_address
}

output "app_url" {
  description = "HTTPS URL expected to serve Friend-Hub after DNS points at the VPS."
  value       = "https://${var.domain_name}"
}

output "ssh_command" {
  description = "SSH command for the non-root deployment user."
  value       = "ssh ${var.deploy_user}@${hcloud_server.friend_hub.ipv4_address}"
}

output "dns_note" {
  description = "Manual DNS reminder."
  value       = "Point ${var.domain_name} A record to ${hcloud_server.friend_hub.ipv4_address} before expecting Caddy HTTPS issuance to succeed."
}
