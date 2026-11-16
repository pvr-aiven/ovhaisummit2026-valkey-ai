#!/usr/bin/env bash
# Copies the env files and compose overrides to the VM (through the load balancer's SSH listener),
# writes secrets.env from env-out/ai-endpoints.key if present, then runs make prepare and make up.
# Usage: ./deploy.sh [demo-dir ...]   (default: the three demos; SSH_KEY=path picks the private key)
set -euo pipefail
cd "$(dirname "$0")"

lb=$(terraform output -raw lb_public_ip)
opts=(-o UserKnownHostsFile=known_hosts -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=30)
[ -n "${SSH_KEY:-}" ] && opts+=(-i "$SSH_KEY")
demos=("$@")
[ ${#demos[@]} -gt 0 ] || demos=(demo-1-recherche-visuelle demo-2-rag demo-3-cache-routage)

ssh "${opts[@]}" "ubuntu@$lb" 'cloud-init status --wait >/dev/null; test -f /var/lib/cloud/instance/summit-ready'

for d in "${demos[@]}"; do
  scp -q "${opts[@]}" "env-out/$d/ovhcloud.env" "ubuntu@$lb:demos/demos/$d/env/ovhcloud.env"
  scp -q "${opts[@]}" "compose-override/$d.override.yml" "ubuntu@$lb:demos/demos/$d/docker-compose.override.yml"
done

# The key goes through stdin, so it never appears in a command line or in the output.
if [ -f env-out/ai-endpoints.key ]; then
  ssh "${opts[@]}" "ubuntu@$lb" 'set -e; umask 077; k=$(tr -d "\r\n"); [ -n "$k" ] || { echo "empty AI Endpoints key" >&2; exit 1; }
    for d in demo-2-rag demo-3-cache-routage; do printf "AI_ENDPOINTS_API_KEY=%s\n" "$k" > "demos/demos/$d/env/secrets.env"; done' \
    < env-out/ai-endpoints.key
fi

for d in "${demos[@]}"; do
  # shellcheck disable=SC2029  # $d is meant to expand locally
  ssh "${opts[@]}" "ubuntu@$lb" "cd demos/demos/$d && chmod 600 env/*.env && make prepare TARGET=ovhcloud && make up TARGET=ovhcloud"
done

echo "UIs: http://$lb:8000 (demo 1), http://$lb:8001 (demo 2), http://$lb:8002 (demo 3)"
