output "project_id" {
  value = var.project_id
}

output "lb_public_ip" {
  value = ovh_cloud_floating_ip.lb.current_state.ip
}

output "valkey_host" {
  value = ovh_cloud_project_database.valkey.endpoints[0].domain
}

output "valkey_port" {
  value = ovh_cloud_project_database.valkey.endpoints[0].port
}

output "valkey_id" {
  value = ovh_cloud_project_database.valkey.id
}

output "gateway_public_ip" {
  value = ovh_cloud_project_gateway.gw.external_information[0].ips[0].ip
}
