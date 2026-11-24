# ☕ 모카: SO-ARM100 바리스타 로봇

[![tests](https://github.com/fbrown35/coffee_robot/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/fbrown35/coffee_robot/actions/workflows/tests.yml)

SO-ARM100 로봇 팔이 필립스 전자동 커피머신(1200 시리즈)을 조작해 커피를 만들고,
Alibaba Cloud Qwen과 연결해 사용자와 대화하는 프로젝트입니다. 대화 중에 농담을 하고, 미리 정한 범주의 뉴스를 전해 주고,
질문에 답합니다. 머신에 경고가 뜨면 바로 알려 줍니다.

```
                       ┌──────────────────── PC (GPU 권장) ────────────────────┐
 사용자 ⇄ 텍스트/음성 ⇄ │ assistant.py ── Qwen (DashScope): 대화·도구 호출·Qwen-VL │
                       │     │  make_coffee / check_machine / get_news            │
                       │     ▼                                                    │
                       │  brew.py (상태 머신) ── panel_monitor.py (LED 판독)      │
                       │     │ /subtask, /start, /reset                           │
                       │     ▼                                                    │
                       │  lerobot-rollout --interactive (SmolVLA 파인튜닝 정책)  │
                       └─────┬───────────────────────────────▲──────────────────┘
                 socat ~/ttyCOFFEE                    ZMQ :5555 (camera_hub)
                             │ WiFi TCP:8888                 │
                        ┌────▼────┐                  ┌───────┴────────┐
                        │  ESP32  │─UART─ 서보 보드 ─ │ camera1(정면)  │
                        └─────────┘   SO-ARM100      │ camera2(손목)  │
                                                     └────────────────┘
```

## 동작 순서

1. "커피 한 잔 만들어줘" → Qwen이 `make_coffee` 도구를 호출합니다.
2. 패널 점검 → (꺼져 있으면) **전원 버튼** → 예열 대기
3. **컵을 집어 추출구 아래에 놓기** → Qwen-VL로 컵 위치 확인, 실패하면 재시도
4. **샷(에스프레소) 버튼** → **시작 버튼** → 추출이 시작됐는지 확인
5. 추출을 기다리는 동안 농담을 하고 "뉴스 들려드릴까요?"라고 묻습니다.
6. 단계마다 ⚠ / 물통 / 찌꺼기통 LED를 확인합니다. 문제가 있으면 **즉시 멈추고** 음성, 콘솔, 휴대폰 푸시(ntfy/텔레그램)로 알립니다.

## 빠른 시작

```bash
pip install -e ".[robot,dev]"            # 음성까지: ".[robot,voice,dev]"
cp config/config.example.yaml config/config.yaml
cp .env.example .env                     # DASHSCOPE_API_KEY 입력
```

로봇 없이 대화와 흐름만 먼저 시험해 볼 수 있습니다. API 키만 있으면 됩니다.

```bash
coffee-robot --dry-run
```

실제 로봇에서는 터미널을 3개 엽니다.

```bash
coffee-wifi-serial        # 1) ESP32 ↔ ~/ttyCOFFEE
```

```bash
coffee-camera-hub         # 2) 카메라 방송
```

```bash
coffee-robot              # 3) 모카 실행 (정책은 첫 커피 요청 때 로딩)
```

## 개발 단계

| 단계 | 할 일 | 문서 |
|---|---|---|
| 1 | ESP32 펌웨어, 배선, 카메라 위치 | [docs/HARDWARE.md](docs/HARDWARE.md) |
| 2 | 캘리브레이션, 텔레옵 연습, **터치 버튼용 전도성 팁** 부착 | [docs/TRAINING.md](docs/TRAINING.md) §3 |
| 3 | 스킬 4개 데모 녹화 (총 50개 이하) | [docs/TRAINING.md](docs/TRAINING.md) §4 |
| 4 | SmolVLA 파인튜닝 (GPU) → `policy.path` 지정 | [docs/TRAINING.md](docs/TRAINING.md) §5 |
| 5 | 스킬별 평가, 보정 데모 | [docs/TRAINING.md](docs/TRAINING.md) §6 |
| 6 | 패널 ROI 캘리브레이션 (`scripts/calibrate_panel.py`) | [docs/HARDWARE.md](docs/HARDWARE.md) §3 |
| 7 | `config.yaml`에서 뉴스 범주, 말투, 알림 설정 | |

## 설정 요점 (`config/config.yaml`)

- `llm.base_url`: 국제 리전은 `dashscope-intl…`, 중국 리전은 `dashscope.aliyuncs.com`
- `llm.chat_model` / `vision_model`: `qwen-plus`, `qwen-vl-max` (Model Studio에서 쓸 수 있는 모델로 변경)
- `llm.persona`: 로봇의 이름, 말투, 농담 정도
- `news.categories`: `{범주 이름: 검색어}` 형식. 오늘(24시간 이내) Google News 헤드라인만 가져오고,
  Qwen은 가져온 기사만 바탕으로 요약합니다.
- `skills.*.task`: 녹화 때 쓴 지시문과 **정확히 같아야** 합니다.
- `notify.ntfy_topic`: 휴대폰에 ntfy 앱을 설치하고 같은 토픽을 구독하면 에러 푸시를 받습니다.

## 구조

```
coffee_robot/
  assistant.py      대화 루프 + 도구 + 이벤트 알림 (진입점: coffee-robot)
  brew.py           커피 시퀀스 상태 머신, 재시도, 에러 중단
  skill_runner.py   lerobot-rollout --interactive 제어 (/subtask, /start, /reset)
  panel_monitor.py  패널 LED 켜짐/깜빡임/경고 판독
  llm.py            DashScope(OpenAI 호환) Qwen 채팅 + Qwen-VL
  news.py           범주별 오늘 뉴스 (RSS)
  voice.py          (선택) Paraformer ASR / CosyVoice TTS
  notify.py         콘솔/음성/ntfy/텔레그램 알림
  camera_hub.py     USB 카메라 → ZMQ (LeRobot ZMQ 카메라 호환)
  wifi_serial.py    ESP32 TCP → 가상 시리얼 포트 (socat)
  lerobot_launcher.py  config 기반 LeRobot 0.7 CLI 래퍼 (calibrate/teleop/record/rollout)
firmware/esp32_bus_bridge/   ESP32 투명 브리지 펌웨어
scripts/            record_all_skills.sh, train.sh, calibrate_panel.py
tests/              pytest (로봇/네트워크 없이 실행)
```

## 테스트

```bash
python -m pytest -q
```

LeRobot은 `0.7.0` 버전에 맞춰 작성했습니다(`pyproject.toml`에서 버전 고정). 다른 버전에서는 CLI 인자가 다를 수 있습니다.
