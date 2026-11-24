# 하드웨어 구성

## 1. 무선 연결: 라즈베리파이 (서보 버스 + 카메라)

```
 SO-ARM100 ─ 서보 드라이버 보드 ─USB─┐
 손목 카메라 ─────────────USB-A─────┼─ 라즈베리파이 ── WiFi ── PC (LeRobot / 대화 / 패널 감시)
 정면 카메라 ─────────────USB-A─────┘     │                       ↑ socat 가상 포트 ~/ttyCOFFEE
                                          ├ coffee-serial-bridge  (TCP 8888)
                                          └ coffee-camera-hub     (ZMQ 5555)
```

설치와 설정은 **[docs/RASPBERRY_PI.md](RASPBERRY_PI.md)** 를 따르세요.
서보 드라이버 보드의 노란 점퍼는 **A (USB)** 위치에 둡니다.

**지연 시간 관련 팁**

- LeRobot이 30Hz로 돌면 한 스텝마다 위치 읽기 1회와 쓰기 1회를 합니다. WiFi 왕복이 10ms를 넘으면 동작이 끊길 수 있습니다.
- 서보 브리지는 TCP 지연 전송(Nagle)을 끄고 카메라보다 높은 우선순위로 돕니다. PC 쪽 버스 타임아웃은 `robot.bus_timeout_ms`(기본 150ms)로 늘렸습니다.
- 파이를 공유기 가까이에 두고 5GHz WiFi를 쓰세요.
- **데이터 수집(녹화) 때는 서보를 PC에 USB로 직결하는 걸 권장합니다.** 지연이 섞인 데모는 품질이 떨어집니다.
  카메라는 반대로 **녹화 때도 실행 때와 같이 파이를 거치게** 하세요. JPEG 압축과 지연이 학습과 실행에서 같아야 합니다.
- 리더 암은 항상 PC에 USB로 직접 연결합니다.

**유선으로 쓰려면**: 서보 보드와 카메라를 PC에 직접 꽂고, PC에서 `coffee-camera-hub` 를 실행한 뒤
`robot.port: /dev/ttyACM0`, `cameras.hub_host: 127.0.0.1` 로 설정합니다.

**비상 정지**: 대화창에 "멈춰"/"정지"를 입력하면 즉시 `/reset`(정지 후 홈 복귀)을 보냅니다. PC와 파이의 연결이 끊기면 서보는
기본적으로 마지막 자세를 유지합니다(`serial_bridge.relax_on_disconnect: false`). 물리적인 전원 차단 스위치도 반드시 손 닿는 곳에 두세요.

## 2. 카메라

| 이름 | 위치 | 용도 |
|---|---|---|
| camera1 | 머신 앞쪽 위에서 비스듬히 내려다봄 | 정책 입력 + **패널 LED 판독** + 컵 확인(Qwen-VL) |
| camera2 | 손목 (사진의 USB 카메라 모듈) | 정책 입력 (컵 잡기/버튼 정밀 위치) |

- 카메라 두 대는 `coffee-camera-hub`가 한 번만 열고 ZMQ로 방송합니다. LeRobot과 패널 감시가 같은 영상을 동시에 씁니다.
- 카메라 경로는 재부팅해도 바뀌지 않는 `/dev/v4l/by-id/...` 를 쓰세요 ([docs/RASPBERRY_PI.md](RASPBERRY_PI.md) §5).

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
