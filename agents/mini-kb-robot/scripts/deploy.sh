#!/usr/bin/env bash
# One-shot install/redeploy script for a systemd-based Linux host (Debian/Ubuntu
# or RHEL/CentOS family). Safe to re-run: picks up code/dependency updates and
# restarts the service.
#
# Usage: ./scripts/deploy.sh [port]   (default port 8000)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="mini-kb-robot"
PORT="${1:-8000}"
RUN_USER="$(whoami)"

cd "$APP_DIR"

echo "==> git pull"
if git -C "$APP_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$APP_DIR" pull --ff-only || echo "!! git pull 失败，手动检查后再继续"
fi

echo "==> system packages"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-venv python3-pip git curl
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3-pip git curl >/dev/null
elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3-pip git curl >/dev/null
else
    echo "!! 未识别的包管理器，请确认 python3/pip/venv/git 已手动装好"
fi

echo "==> python venv"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "==> .env"
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "!! 新建了 .env，需要填 ARK_API_KEY / ARK_MODEL 等值。"
    read -rp "编辑完 .env 后按回车继续..." _
fi

echo "==> systemd service"
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=${SERVICE_NAME}
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn api.server:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "==> firewall"
if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow "${PORT}/tcp" || true
elif command -v firewall-cmd >/dev/null 2>&1; then
    sudo firewall-cmd --add-port="${PORT}/tcp" --permanent
    sudo firewall-cmd --reload
else
    echo "!! 没找到 ufw/firewall-cmd，手动确认 ${PORT} 端口已放行（云厂商安全组也要单独放行）"
fi

echo "==> health check"
sleep 2
if curl -fsS "http://127.0.0.1:${PORT}/health"; then
    echo
    echo "==> 部署完成。日志: journalctl -u ${SERVICE_NAME} -f"
else
    echo
    echo "!! health check 失败，看日志排查: journalctl -u ${SERVICE_NAME} -f"
    exit 1
fi
