#!/usr/bin/env bash
# Installs the Perch agent as a systemd service (starts on boot, restarts on failure).
# Usage:  sudo ./install_agent_linux.sh [port]      (default port 9123)
set -euo pipefail
PORT="${1:-9123}"
HERE="$(cd "$(dirname "$0")" && pwd)"

install -Dm755 "$HERE/perch_agent.py" /opt/perch/perch_agent.py

cat > /etc/systemd/system/perch-agent.service <<EOF
[Unit]
Description=Perch agent (serves nvidia-smi stats on port $PORT)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/env python3 /opt/perch/perch_agent.py --port $PORT
Restart=always
RestartSec=5
DynamicUser=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now perch-agent
sleep 1
systemctl --no-pager --lines=0 status perch-agent || true

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" comment "Perch agent"
fi

echo
echo "Test it:  curl http://localhost:$PORT/gpus"
