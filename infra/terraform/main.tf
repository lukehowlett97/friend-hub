locals {
  name           = "${var.project_name}-${var.environment}"
  ssh_public_key = file(pathexpand(var.ssh_public_key_path))

  labels = {
    project     = var.project_name
    environment = var.environment
    managed-by  = "terraform"
  }

  user_data = templatefile("${path.module}/templates/cloud-init.yml.tftpl", {
    project_name   = var.project_name
    deploy_user    = var.deploy_user
    ssh_public_key = local.ssh_public_key
  })
}

resource "hcloud_ssh_key" "friend_hub" {
  name       = "${local.name}-ssh-key"
  public_key = local.ssh_public_key
  labels     = local.labels
}

resource "hcloud_firewall" "friend_hub" {
  name   = "${local.name}-firewall"
  labels = local.labels

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.allowed_ssh_ips
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction       = "out"
    protocol        = "icmp"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "friend_hub" {
  name         = local.name
  image        = "ubuntu-24.04"
  server_type  = var.server_type
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.friend_hub.id]
  firewall_ids = [hcloud_firewall.friend_hub.id]
  user_data    = local.user_data
  labels       = local.labels
}
