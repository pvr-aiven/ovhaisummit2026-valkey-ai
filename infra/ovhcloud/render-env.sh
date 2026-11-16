#!/usr/bin/env bash
# Resets the Valkey "default" password through the API, then writes demos/*/env/ovhcloud.env (0600)
# under ./env-out following each demo's env/ovhcloud.env.example. The password never reaches stdout.
# AI_ENDPOINTS_API_KEY is not handled here: deploy.sh writes secrets.env from env-out/ai-endpoints.key.
set -euo pipefail
cd "$(dirname "$0")"

api=./ovhapi.py
project=$(terraform output -raw project_id)
cluster=$(terraform output -raw valkey_id)
host=$(terraform output -raw valkey_host)
port=$(terraform output -raw valkey_port)

umask 077
out=env-out
mkdir -p "$out"/demo-{1-recherche-visuelle,2-rag,3-cache-routage}

user=$(python3 -I "$api" GET "/cloud/project/$project/database/valkey/$cluster/user" | tail -n +2 |
  python3 -I -c 'import json, sys; print(json.load(sys.stdin)[0])')
python3 -I "$api" POST "/cloud/project/$project/database/valkey/$cluster/user/$user/credentials/reset" '' \
  --secret-out "$out/valkey-default.pw" | head -1 | grep -qx 200 || { echo "password reset failed" >&2; exit 1; }

# URL-encode the password; compose interpolates "$" in env files, so refuse it rather than escape it.
pw=$(python3 -I -c 'import sys, urllib.parse
p = open(sys.argv[1]).read()
sys.exit("password contains $, run this script again") if "$" in p else print(urllib.parse.quote(p, safe=""), end="")' "$out/valkey-default.pw")
url="rediss://default:${pw}@${host}:${port}"
ai="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"

printf '%s\n' "DEMO_TARGET=ovhcloud" "VALKEY_URL=$url" \
  > "$out/demo-1-recherche-visuelle/ovhcloud.env"

printf '%s\n' "DEMO_TARGET=ovhcloud" "VALKEY_URL=$url" \
  "EMBED_BASE_URL=$ai" "EMBED_MODEL=bge-m3" \
  "CHAT_BASE_URL=$ai" "CHAT_MODEL=Mistral-Small-3.2-24B-Instruct-2506" \
  > "$out/demo-2-rag/ovhcloud.env"

printf '%s\n' "DEMO_TARGET=ovhcloud" "VALKEY_URL=$url" \
  "EMBED_BASE_URL=$ai" "EMBED_MODEL=bge-m3" \
  "CHAT_BASE_URL=$ai" "SIMPLE_MODEL=Mistral-Small-3.2-24B-Instruct-2506" "COMPLEX_MODEL=gpt-oss-120b" \
  > "$out/demo-3-cache-routage/ovhcloud.env"

echo "wrote $out/*/ovhcloud.env (host $host, port $port)"
