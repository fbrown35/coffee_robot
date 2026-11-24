#!/usr/bin/env bash
# 라즈베리파이 설치: 카메라 허브 + 서보 버스 브리지를 systemd 서비스로 등록
#   cd ~/coffee_robot && ./deploy/pi/install.sh
# 다시 실행해도 안전함 (업데이트 후 재설치에도 사용).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICES=(coffee-camera-hub coffee-serial-bridge)

echo "== 패키지 설치"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-dev v4l-utils libgl1 libglib2.0-0

echo "== 가상환경 + 파이썬 패키지 (로봇 학습용 lerobot/torch 는 설치하지 않음)"
if [[ ! -d "${REPO}/.venv" ]]; then
  python3 -m venv "${REPO}/.venv"
fi
"${REPO}/.venv/bin/pip" install -q --upgrade pip
"${REPO}/.venv/bin/pip" install -q -e "${REPO}[pi]"

echo "== 장치 권한 (시리얼: dialout, 카메라: video)"
sudo usermod -aG dialout,video "${USER_NAME}"

if [[ ! -f "${REPO}/config/config.yaml" ]]; then
  cp "${REPO}/config/config.example.yaml" "${REPO}/config/config.yaml"
  echo "!! config/config.yaml 을 만들었습니다. cameras.devices 와 serial_bridge.device 를 확인하세요."
fi

echo "== systemd 서비스 등록"
for svc in "${SERVICES[@]}"; do
  sed -e "s|@USER@|${USER_NAME}|g" -e "s|@REPO@|${REPO}|g" \
    "${REPO}/deploy/pi/${svc}.service" | sudo tee "/etc/systemd/system/${svc}.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICES[@]}"
sudo systemctl restart "${SERVICES[@]}"

echo
echo "== 상태"
systemctl --no-pager --lines=0 status "${SERVICES[@]}" || true
echo
echo "로그: journalctl -u coffee-serial-bridge -u coffee-camera-hub -f"
echo "PC 의 config.yaml: wifi_serial.host 와 cameras.hub_host 를 이 파이 주소($(hostname).local)로 설정"
