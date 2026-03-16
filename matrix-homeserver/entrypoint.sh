#!/bin/sh
set -eu

CONFIG_PATH="${SYNAPSE_CONFIG_PATH:-/data/homeserver.yaml}"
SERVER_NAME="${MATRIX_SERVER_NAME:-${SYNAPSE_SERVER_NAME:-localhost}}"
REPORT_STATS="${MATRIX_REPORT_STATS:-${SYNAPSE_REPORT_STATS:-no}}"
HTTP_PORT="${MATRIX_HTTP_PORT:-8008}"

if [ ! -f "$CONFIG_PATH" ]; then
  echo "[matrix-synapse] generating config for server_name=$SERVER_NAME" >&2
  export SYNAPSE_SERVER_NAME="$SERVER_NAME"
  export SYNAPSE_REPORT_STATS="$REPORT_STATS"
  export SYNAPSE_HTTP_PORT="$HTTP_PORT"

  /start.py generate
  echo "[matrix-synapse] generated $CONFIG_PATH" >&2
fi

# Always patch a couple of local-friendly settings idempotently.
python - <<'PY'
import os
import secrets
import yaml

path = os.environ.get('SYNAPSE_CONFIG_PATH', '/data/homeserver.yaml')
with open(path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

# Local testing defaults. This is not safe for an internet-exposed server.
# Needed so Element X can create an account on a LAN/VPN-only server.
cfg.setdefault('enable_registration', True)
cfg.setdefault('enable_registration_without_verification', True)

# If provided, set a stable public_baseurl (clients can be picky about this).
# Examples:
# - http://mac-workstation:8008
# - https://mac-workstation (when using the TLS proxy on 443)
public_baseurl = os.environ.get('MATRIX_PUBLIC_BASE_URL')
if public_baseurl:
    if not public_baseurl.endswith('/'):
        public_baseurl += '/'
    cfg['public_baseurl'] = public_baseurl

# Provide shared secret for admin/user creation tooling.
if not cfg.get('registration_shared_secret'):
    cfg['registration_shared_secret'] = secrets.token_hex(32)

# Ensure http listener binds on all interfaces.
listeners = cfg.get('listeners')
if isinstance(listeners, list):
    for l in listeners:
        if isinstance(l, dict) and l.get('type') == 'http':
            l.setdefault('bind_addresses', ['0.0.0.0'])

with open(path, 'w', encoding='utf-8') as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
PY

exec /start.py
