# 하드웨어 구성

## 1. ESP32 무선 브리지 (서보 버스)

```
 PC (LeRobot) ─ WiFi ─ ESP32 ─ UART 1Mbps ─ 버스 서보 드라이버 보드 ─ STS3215 ×6 (SO-ARM100)
       ↑ socat 가상포트 ~/ttyCOFFEE
```

**배선** (사진의 Waveshare Bus Servo Adapter 기준. 다른 보드면 실크 인쇄를 확인하세요)

| ESP32 | 드라이버 보드 |
|---|---|
| GPIO17 (TX2) | RX |
| GPIO16 (RX2) | TX |
| GND | GND |

- 보드의 노란 점퍼를 **B (UART)** 위치로 옮깁니다. A는 USB 모드입니다.
- ESP32 전원은 별도 5V USB 전원으로 공급하는 것이 안전합니다. 서보가 움직일 때 생기는 전압 강하로 ESP32가 리셋될 수 있습니다.
- 보드에 이미 ESP32가 달린 버전(Waveshare General Driver for Robots 등)이면 그 ESP32에 바로 펌웨어를 올리면 되고, 핀 번호만 바꾸세요.

**펌웨어**

1. `firmware/esp32_bus_bridge/secrets.example.h` 파일을 `secrets.h`로 복사하고 WiFi 정보를 넣습니다.
2. Arduino IDE → 보드 "ESP32 Dev Module" → 업로드.
3. 시리얼 모니터(115200)에 IP가 표시됩니다. 같은 네트워크의 PC에서 `coffee-wifi-serial --check` 실행.

**지연 시간 관련 팁**

- LeRobot이 30Hz로 돌면 한 스텝마다 위치 읽기 1회와 쓰기 1회를 합니다. WiFi 왕복이 10ms를 넘으면 동작이 끊길 수 있습니다.
- 펌웨어에서 WiFi 절전과 Nagle을 껐고, PC 쪽 버스 타임아웃은 `robot.bus_timeout_ms`(기본 150ms)로 늘렸습니다.
- 공유기 가까이에 두고, 가능하면 5GHz를 지원하는 ESP32-C5 또는 전용 2.4GHz AP를 쓰세요.
- **데이터 수집(녹화) 때는 유선 USB를 권장합니다.** 지연이 섞인 데모는 품질이 떨어집니다. 학습된 정책을 실행할 때만 무선을 써도 됩니다.
- 리더 암은 항상 PC에 USB로 직접 연결합니다.

**비상 정지**: 대화창에 "멈춰"/"정지"를 입력하면 즉시 `/reset`(정지 후 홈 복귀)을 보냅니다. WiFi가 끊기면 ESP32는 기본적으로 마지막
자세를 유지합니다(`RELAX_ON_DISCONNECT=0`). 물리적인 전원 차단 스위치도 반드시 손 닿는 곳에 두세요.

## 2. 카메라

| 이름 | 위치 | 용도 |
|---|---|---|
| camera1 | 머신 앞쪽 위에서 비스듬히 내려다봄 | 정책 입력 + **패널 LED 판독** + 컵 확인(Qwen-VL) |
| camera2 | 손목 (사진의 USB 카메라 모듈) | 정책 입력 (컵 잡기/버튼 정밀 위치) |

- 카메라 두 대는 `coffee-camera-hub`가 한 번만 열고 ZMQ로 방송합니다. LeRobot과 패널 감시가 같은 영상을 동시에 씁니다.
- **카메라까지 완전히 무선으로 하려면**: 로봇 옆에 라즈베리파이(4/5 또는 Zero 2W)를 두고 USB 카메라 두 대를 연결한 뒤
  거기서 `coffee-camera-hub`를 실행합니다. PC의 `config.yaml`에서 `cameras.hub_host`를 파이의 IP로 바꾸면 됩니다.
  (ESP32는 USB 카메라(UVC)를 30fps로 중계할 성능이 부족해서 서보 버스 전용으로 씁니다.)
- `lerobot-find-cameras opencv`로 카메라 번호를 확인해서 `cameras.devices.*.index_or_path`에 넣습니다.

## 3. 커피머신 패널 판독

```bash
python scripts/calibrate_panel.py rois        # 머신 ON, 경고 없음: 아이콘마다 드래그
python scripts/calibrate_panel.py reference   # 머신 OFF: 꺼진 밝기 기준 저장
python scripts/calibrate_panel.py test        # 실시간 확인 (경고를 일부러 띄워 보세요: 물통 빼기 등)
```

판독하는 아이콘과 대응 방법:

| 아이콘 | 의미 | 로봇 동작 |
|---|---|---|
| ⚠ 경고 | 추출 유닛 / 도어 / 내부 오류 | **중단** 후 알림 |
| 물통 | 물 부족 / 물통 빠짐 | **중단** 후 알림 |
| 찌꺼기통 | 가득 참 / 빠짐 | **중단** 후 알림 |
| Calc/Clean | 석회 제거 필요 | 알림만 하고 계속 |
| Aqua Clean | 필터 교체 | 알림만 하고 계속 |
| 음료 버튼 깜빡임 | 예열 / 추출 중 | 대기 |

아이콘의 정확한 의미와 깜빡임 패턴은 머신 사용설명서의 "표시등" 항목과 비교해 보세요.
`panel_monitor.py`의 `ALERTS` 문구를 그에 맞게 고치면 됩니다.
ROI를 설정하지 않으면 Qwen-VL이 사진을 보고 판단하는 방식으로 대신합니다. 이 경우 느리고 정확도도 낮습니다.
