variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "EU-WEST-PAR"
}

variable "subnet_cidr" {
  type    = string
  default = "10.42.0.0/24"
}

variable "vm_ip" {
  type    = string
  default = "10.42.0.10"
}

variable "image_id" {
  description = "Ubuntu 24.04 in the region (GET /cloud/project/{id}/image)."
  type        = string
}

variable "flavor_id" {
  description = "b3-16 in the region (GET /cloud/project/{id}/flavor)."
  type        = string
}

variable "lb_flavor_id" {
  description = "Load balancer flavor 'small' (GET /cloud/project/{id}/region/{region}/loadbalancing/flavor)."
  type        = string
  default     = "472f72ea-3e6a-4633-bf23-0591bef5c553"
}

variable "ssh_public_key" {
  type = string
}

variable "admin_cidr" {
  description = "Only source allowed on the SSH listener."
  type        = string
}

variable "demo_cidrs" {
  description = "Sources allowed on the demo listeners (laptop, venue egress)."
  type        = list(string)
}

variable "repo_url" {
  type    = string
  default = "https://github.com/pvr-aiven/ovhsummit2006-valkey-ai.git"
}

variable "repo_commit" {
  type    = string
  default = "a9b2f7ef28e621aac1a38247e9bc7979e971aa29"
}
