#!/usr/bin/env bash
# Installs the GPU Watch agent as a systemd service (starts on boot, restarts on failure).
# Usage:  sudo ./install_agent_linux.sh [port]      (default port 9123)
set -euo pipefail
PORT="${1:-9123}"
HERE="$(cd "$(dirname "$0")" && pwd)"

install -Dm755 "$HERE/gpu_agent.py" /opt/gpu-watch/gpu_agent.py

cat > /etc/systemd/system/gpu-watch-agent.service <<EOF
[Unit]
Description=GPU Watch agent (serves nvidia-smi stats on port $PORT)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/env python3 /opt/gpu-watch/gpu_agent.py --port $PORT
Restart=always
RestartSec=5
DynamicUser=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now gpu-watch-agent
sleep 1
systemctl --no-pager --lines=0 status gpu-watch-agent || true

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" comment "GPU Watch agent"
fi

echo
echo "Test it:  curl http://localhost:$PORT/gpus"
