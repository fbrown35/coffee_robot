# 라즈베리파이 설치 (서보 버스 + 카메라 무선 연결)

로봇 옆에 라즈베리파이 한 대를 두고, 서보 드라이버 보드와 USB-A 카메라 두 대를 모두 파이에 꽂습니다.
파이는 두 가지 서비스를 실행하고, PC는 WiFi로 접속합니다.

```
 SO-ARM100 ─ 서보 드라이버 보드 ─USB─┐
 손목 카메라 (camera2) ──────USB-A──┼─ 라즈베리파이 ─ WiFi ─ PC (정책 실행 / 대화 / 패널 감시)
 정면 카메라 (camera1) ──────USB-A──┘
   coffee-serial-bridge  : USB 시리얼 ↔ TCP 8888   → PC: coffee-wifi-serial 이 ~/ttyCOFFEE 로 연결
   coffee-camera-hub     : 카메라 → ZMQ 5555       → PC: LeRobot ZMQ 카메라 + 패널 감시가 구독
```

## 1. 준비물

| 항목 | 권장 | 비고 |
|---|---|---|
| 보드 | Raspberry Pi 4 (2GB 이상) 또는 Pi 5 | USB-A 포트 4개 |
| 저장장치 | microSD 16GB 이상 | |
| 전원 | Pi 4: 5V 3A / Pi 5: 5V 5A | 서보 전원에서 강압 컨버터(5V, 5A 이상)로 따오면 전원선 하나로 됨 |
| 네트워크 | 5GHz WiFi | 카메라 두 대에 약 20Mbps |

Pi Zero 2 W도 동작은 하지만 USB 포트가 하나뿐이라 OTG 허브가 필요하고, 640×480 30fps 카메라 두 대를
JPEG로 인코딩하기에는 CPU가 빠듯합니다.

## 2. OS 설치

1. Raspberry Pi Imager로 **Raspberry Pi OS Lite (64-bit)** 를 굽습니다.
2. 굽기 전 설정(톱니바퀴)에서 다음을 지정합니다.
   - 호스트 이름: `coffee-pi` → 네트워크에서 `coffee-pi.local` 로 접속됩니다.
   - 사용자 이름과 비밀번호
   - WiFi SSID와 비밀번호, 국가 `KR`
   - SSH 사용
3. 부팅한 뒤 PC에서 접속합니다.
   ```bash
   ssh <사용자>@coffee-pi.local
   ```

## 3. 배선

- **서보 드라이버 보드**: 노란 점퍼를 **A (USB)** 위치에 두고 USB 케이블로 파이에 연결합니다.
  서보 전원(어댑터)은 따로 보드에 연결합니다.
- **카메라 두 대**: 파이의 USB-A 포트에 연결합니다. Pi 4는 파란색(USB 3.0) 포트를 쓰는 걸 권장합니다.
- **손목 카메라 케이블**: 팔을 따라 베이스까지 여유 있게 묶습니다. 관절이 움직일 때 케이블이 당기지 않아야 합니다.

## 4. 설치

```bash
sudo apt-get install -y git
```

```bash
git clone https://github.com/fbrown35/coffee_robot.git ~/coffee_robot
```

```bash
cd ~/coffee_robot && ./deploy/pi/install.sh
```

설치 스크립트가 하는 일:

- 가상환경(`.venv`)을 만들고 `pip install -e ".[pi]"` 를 실행합니다. lerobot과 torch는 설치하지 않습니다.
- 사용자를 `dialout`(시리얼)과 `video`(카메라) 그룹에 추가합니다.
- `config/config.yaml` 이 없으면 예제를 복사합니다.
- `coffee-serial-bridge`, `coffee-camera-hub` 서비스를 등록하고 시작합니다. 부팅할 때 자동으로 시작됩니다.

그룹 권한은 다시 로그인해야 적용됩니다. 서비스는 설치 직후부터 정상 동작하지만, 직접 명령을 실행해 보려면
한 번 로그아웃했다가 다시 접속하세요.

## 5. 파이 설정 (`config/config.yaml`)

장치를 확인합니다.

```bash
ls -l /dev/serial/by-id/
```

```bash
v4l2-ctl --list-devices
```

```yaml
serial_bridge:
  device: auto        # 시리얼 장치가 하나면 auto. 여러 개면 /dev/serial/by-id/usb-... 경로를 그대로 적기
  baud: 1000000
  port: 8888

cameras:
  devices:
    camera1: {index_or_path: /dev/v4l/by-id/<정면 카메라>-video-index0, width: 640, height: 480, fps: 30}
    camera2: {index_or_path: /dev/v4l/by-id/<손목 카메라>-video-index0, width: 640, height: 480, fps: 30}
```

카메라 번호(`0`, `2` 같은 숫자)는 재부팅하면 바뀔 수 있습니다. `/dev/v4l/by-id/...` 경로를 쓰면 항상 같은 카메라를
가리킵니다. 같은 모델의 카메라 두 대라서 by-id 이름이 같다면 `/dev/v4l/by-path/...` 를 쓰세요(꽂은 포트 기준).

설정을 바꾼 뒤에는 서비스를 다시 시작합니다.

```bash
sudo systemctl restart coffee-serial-bridge coffee-camera-hub
```

## 6. PC 설정

PC의 `config/config.yaml`:

```yaml
robot:
  port: ~/ttyCOFFEE
wifi_serial:
  host: coffee-pi.local
  port: 8888
cameras:
  hub_host: coffee-pi.local
```

PC에서 연결을 확인합니다.

```bash
coffee-wifi-serial --check
```

이후에는 평소대로 PC에서 `coffee-wifi-serial` 을 켜 두고 `coffee-lerobot ...` 이나 `coffee-robot` 을 실행합니다.

## 7. 운영

| 할 일 | 명령 |
|---|---|
| 상태 보기 | `systemctl status coffee-serial-bridge coffee-camera-hub` |
| 실시간 로그 | `journalctl -u coffee-serial-bridge -u coffee-camera-hub -f` |
| 재시작 | `sudo systemctl restart coffee-serial-bridge coffee-camera-hub` |
| 업데이트 | `cd ~/coffee_robot && git pull && ./deploy/pi/install.sh` |
| 자동 시작 끄기 | `sudo systemctl disable --now coffee-serial-bridge coffee-camera-hub` |

## 8. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 로그에 `serial not available` 이 반복됨 | 보드 USB 연결, 점퍼가 **A** 위치인지, `ls /dev/serial/by-id/` |
| PC에서 `--check` 결과가 `UNREACHABLE` | 같은 네트워크인지, `ping coffee-pi.local`. mDNS가 안 되면 IP를 직접 적기 |
| LeRobot 실행 중 모터 읽기 실패가 잦음 | WiFi 신호(5GHz 권장), PC `robot.bus_timeout_ms` 를 200~300으로 늘리기 |
| 카메라 영상이 끊기거나 느림 | `camera_hub` 로그, `cameras.jpeg_quality` 를 70으로 낮추기, 카메라를 USB 3.0 포트에 꽂기 |
| 카메라 하나가 안 나옴 | `v4l2-ctl --list-devices` 로 경로 확인, 두 카메라를 다른 USB 컨트롤러 포트에 꽂기 |

**비상 정지**: 대화창에 "멈춰"를 입력하면 정책이 즉시 멈추고 홈 자세로 돌아갑니다. PC와 파이의 연결이 끊기면
서보는 마지막 자세를 유지합니다(`relax_on_disconnect: false`). 물리적인 전원 차단 스위치도 반드시 손 닿는 곳에 두세요.
