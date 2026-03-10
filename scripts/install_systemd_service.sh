#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/attendance-system}"
SERVICE_NAME="attendance-system.service"
SERVICE_SRC="deploy/systemd/${SERVICE_NAME}"
ENV_SRC="deploy/systemd/attendance-system.env.example"
ENV_DEST_DIR="/etc/attendance-system"
ENV_DEST="${ENV_DEST_DIR}/attendance-system.env"
SYSTEMD_DEST="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -f "${SERVICE_SRC}" ]]; then
  echo "Missing ${SERVICE_SRC}" >&2
  exit 1
fi

sudo mkdir -p "${ENV_DEST_DIR}"
sudo cp "${SERVICE_SRC}" "${SYSTEMD_DEST}"

if [[ ! -f "${ENV_DEST}" ]]; then
  sudo cp "${ENV_SRC}" "${ENV_DEST}"
  echo "Created ${ENV_DEST}. Update it before starting the service."
fi

sudo sed -i "s|/opt/attendance-system|${PROJECT_DIR}|g" "${SYSTEMD_DEST}"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

echo "Installed ${SERVICE_NAME}."
echo "Review ${ENV_DEST}, then start with: sudo systemctl start ${SERVICE_NAME}"
