terraform {
  required_version = ">= 1.9"
  required_providers {
    ovh = {
      source  = "ovh/ovh"
      version = "~> 2.24"
    }
  }
}

# Credentials come from ~/.ovh.conf or the OVH_* environment variables.
provider "ovh" {
  endpoint = "ovh-eu"
}
