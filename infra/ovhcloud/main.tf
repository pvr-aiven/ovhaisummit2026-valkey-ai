locals {
  name       = "summit-valkey"
  network_id = ovh_cloud_project_network_private.net.regions_openstack_ids[var.region]
  # Demo UIs: demo 1 on 8000, demo 2 on 8001, demo 3 on 8002.
  demo_ports = [8000, 8001, 8002]
}

resource "ovh_cloud_project_network_private" "net" {
  service_name = var.project_id
  name         = "${local.name}-net"
  regions      = [var.region]
  vlan_id      = 0
}

# The database service requires a gateway IP on its subnet.
resource "ovh_cloud_project_network_private_subnet_v2" "subnet" {
  service_name      = var.project_id
  region            = var.region
  network_id        = local.network_id
  name              = "${local.name}-subnet"
  cidr              = var.subnet_cidr
  dhcp              = true
  enable_gateway_ip = true
}

# SNAT for the private-only VM: AI Endpoints, PyPI, Docker Hub, Hugging Face.
resource "ovh_cloud_project_gateway" "gw" {
  service_name = var.project_id
  name         = "${local.name}-gw"
  region       = var.region
  model        = "s"
  network_id   = local.network_id
  subnet_id    = ovh_cloud_project_network_private_subnet_v2.subnet.id
}

resource "ovh_cloud_project_database" "valkey" {
  service_name = var.project_id
  description  = "${local.name}-db"
  engine       = "valkey"
  version      = "9.1"
  plan         = "discovery"
  flavor       = "b3-4"

  nodes {
    region     = var.region
    network_id = local.network_id
    subnet_id  = ovh_cloud_project_network_private_subnet_v2.subnet.id
  }

  # Only the private subnet: an empty list would deny everything.
  ip_restrictions {
    ip          = var.subnet_cidr
    description = "summit private subnet"
  }
}

# The demos connect as "default": Valkey Search (FT.*) can't be granted to a custom user through the API.
# Its password is reset by render-env.sh, not here: ovh_cloud_project_database_valkey_user named "default"
# panics in provider 2.24.0 (data_cloud_project_database_valkey_user.go:86, d.Get("id") is nil on create).

resource "ovh_cloud_project_instance" "vm" {
  service_name   = var.project_id
  region         = var.region
  billing_period = "hourly"
  name           = "${local.name}-vm"

  boot_from {
    image_id = var.image_id
  }
  flavor {
    flavor_id = var.flavor_id
  }
  ssh_key_create {
    name       = "${local.name}-key"
    public_key = var.ssh_public_key
  }

  # Private only: no public interface, outbound through the gateway.
  network {
    private {
      ip = var.vm_ip
      network {
        id        = local.network_id
        subnet_id = ovh_cloud_project_network_private_subnet_v2.subnet.id
      }
      gateway {
        id = ovh_cloud_project_gateway.gw.id
      }
    }
  }

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    repo_url    = var.repo_url
    repo_commit = var.repo_commit
  })
}

# The only public entry point. The floating IP is its own resource so it outlives the load balancer:
# ovh_cloud_project_loadbalancer recreates itself on any listener change (adding the venue's CIDR),
# and the public IP must not change. The new ovh_cloud_loadbalancer would update in place, but its
# API v2 call needs the IAM action loadbalancer/usePublicIP, which an ~/.ovh.conf application key can't carry.
resource "ovh_cloud_floating_ip" "lb" {
  service_name = var.project_id
  region       = var.region
  description  = "${local.name}-lb"
}

resource "ovh_cloud_project_loadbalancer" "lb" {
  service_name = var.project_id
  region_name  = var.region
  flavor_id    = var.lb_flavor_id
  name         = "${local.name}-lb"

  network = {
    private = {
      network = {
        id        = local.network_id
        subnet_id = ovh_cloud_project_network_private_subnet_v2.subnet.id
      }
      gateway = {
        id = ovh_cloud_project_gateway.gw.id
      }
      floating_ip = {
        id = ovh_cloud_floating_ip.lb.current_state.id
      }
    }
  }

  listeners = concat(
    [{
      name          = "ssh"
      port          = 22
      protocol      = "tcp"
      allowed_cidrs = [var.admin_cidr]
      pool = {
        name      = "ssh"
        protocol  = "tcp"
        algorithm = "roundRobin"
        members   = [{ name = "vm", address = var.vm_ip, protocol_port = 22 }]
      }
    }],
    # TCP pass-through so the SSE answer streams of demos 2 and 3 are never buffered. The data
    # timeouts cover a gpt-oss-120b answer (the demo's own timeout is 180 s).
    [for p in local.demo_ports : {
      name                = "demo-${p}"
      port                = p
      protocol            = "tcp"
      allowed_cidrs       = var.demo_cidrs
      timeout_client_data = 300000
      timeout_member_data = 300000
      pool = {
        name      = "demo-${p}"
        protocol  = "tcp"
        algorithm = "roundRobin"
        members   = [{ name = "vm", address = var.vm_ip, protocol_port = p }]
      }
    }],
  )
}
