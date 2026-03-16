#!/bin/sh
set -eu

TLS_PORT="${MATRIX_TLS_PORT:-8448}"

# Used for Matrix client discovery. Set this to a stable hostname that matches your TLS certificate.
# Examples:
# - https://mac-workstation (recommended if you publish 443)
# - https://mac-workstation.tailXXXX.ts.net (recommended on Tailscale)
# - https://mac-workstation:8448 (only if you intend clients to use :8448)
BASE_URL="${MATRIX_PUBLIC_BASE_URL:-https://{host}}"

# Used for federation discovery (optional). Defaults to the inbound Host header.
SERVER_NAME="${MATRIX_PUBLIC_SERVER_NAME:-{host}}"

cat > /etc/caddy/Caddyfile <<EOF
{
  storage file_system {
    root /data
  }

  # Prefer HTTP/1.1 + HTTP/2; some clients/networks can be flaky with HTTP/3 (QUIC).
  servers {
    protocols h1 h2
  }

  # On-demand TLS is used so clients can connect via LAN IP / Tailnet IP / MagicDNS.
  # (No global ask/permission configured; keep this service LAN/VPN-only.)
}

:${TLS_PORT} {
  tls internal {
    on_demand
  }

  # Matrix client discovery.
  handle /.well-known/matrix/client {
    header Content-Type application/json
    respond "{\"m.homeserver\":{\"base_url\":\"$BASE_URL\"}}"
  }

  # Federation discovery (not required for Element X).
  handle /.well-known/matrix/server {
    header Content-Type application/json
    respond "{\"m.server\":\"$SERVER_NAME\"}"
  }

  reverse_proxy matrix-synapse:8008
}
EOF

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
