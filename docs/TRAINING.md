# 훈련 가이드 — 데모 50개 이하로 커피 만들기 학습

## 0. 한눈에 보기: SmolVLA 파인튜닝이란?

`lerobot/smolvla_base`는 **이미 수많은 SO-100 로봇 영상으로 "로봇 팔 쓰는 법"을 배운 모델**입니다.
카메라 영상, 현재 관절 각도, 영어 지시문("press the start button")을 받아서 앞으로 1~2초 동안의 관절 움직임을 내놓습니다.

파인튜닝은 이 모델에게 **우리 커피머신과 우리 팔에서만 통하는 동작을 짧게 추가로 가르치는 것**입니다.
처음부터 배우는 게 아니라서 데모 수십 개로도 충분합니다. 운전을 이미 할 줄 아는 사람에게 새 동네 길만 알려 주는 것과 비슷합니다.

| 순서 | 할 일 | 어디서 | 명령 / 문서 |
|---|---|---|---|
| ① | 학습용 GPU 환경 구성 + 점검 | GPU 머신 | `./scripts/setup_train_env.sh` → `./scripts/check_train_env.sh` (§5-1) |
| ② | 로봇 캘리브레이션, 텔레옵 연습 | 로봇 PC | `coffee-lerobot calibrate` / `teleop` (§4) |
| ③ | 스킬 4개 데모 녹화 (총 50개 이하) | 로봇 PC | `./scripts/record_all_skills.sh` (§2~4) |
| ④ | 데이터셋을 GPU 머신으로 옮기기 | | Hub 업로드 또는 폴더 복사 (§5-2) |
| ⑤ | 파인튜닝 | GPU 머신 | `./scripts/train.sh smolvla <hf_user>/coffee_skills` (§5-3) |
| ⑥ | 체크포인트를 로봇 PC로 가져와 스킬별 평가, 부족하면 데모 보충 | 로봇 PC | §6 |

로봇 PC에 좋은 GPU가 있으면 ①~⑥을 모두 한 컴퓨터에서 해도 됩니다.

## 1. 방법 선택: SmolVLA 파인튜닝 + 스킬 분해

| | **SmolVLA 파인튜닝 (권장)** | ACT (처음부터 학습) |
|---|---|---|
| 사전학습 | SO-100 커뮤니티 데이터로 사전학습된 VLA (약 4.5억 파라미터) | 없음 |
| 언어 지시 | O → 모델 하나로 여러 스킬을 지시문으로 전환 | X → 스킬마다 모델 하나 |
| 필요한 데모 | 스킬당 8~20개면 시작 가능 | 스킬당 30~50개 권장 |
| 추론 | GPU 권장 (RTC 비동기 추론) | 노트북 CPU/GPU 가능 |

**전체 과정을 한 번에 학습하지 않고 4개 스킬로 나눕니다.** 전원부터 추출까지 한 번에 하는 긴 데모는
50개로는 부족하고, 실패했을 때 어디서 틀렸는지도 알 수 없습니다. 스킬로 나누면:

- 각 스킬이 짧아서(5~20초) 데모 몇 개로도 잘 배웁니다.
- 순서·대기·에러 판정은 학습이 아니라 **코드(`brew.py`)와 카메라**가 맡습니다.
- 실패한 스킬만 다시 시도하거나 데모를 보충할 수 있습니다.

## 2. 데모 예산 (총 50개 이하)

| 스킬 | 지시문 (`config.yaml` → `skills`) | 데모 수 | 길이 |
|---|---|---|---|
| power_on | press the power button of the coffee machine | 8 | ~8초 |
| place_cup | pick up a paper cup and place it under the coffee spout | 22 | ~20초 |
| press_shot | press the espresso button | 8 | ~8초 |
| press_start | press the start button | 8 | ~8초 |
| **(예비)** | 평가에서 실패한 상황을 이어받아 고치는 보정 데모 | ≤ 4 | |
| **합계** | | **≤ 50** | |

컵 집기가 가장 어려우니 데모를 가장 많이 씁니다. 버튼 누르기는 위치가 고정이라 적게 들어갑니다.

## 3. 녹화 전 준비 (결과를 크게 좌우함)

1. **터치 버튼 대비**: 필립스 1200 시리즈 패널은 **정전식 터치**입니다. 플라스틱 그리퍼로 누르면 반응하지 않습니다.
   그리퍼 손가락 끝에 **정전식 스타일러스 팁**(전도성 고무)을 붙이고, 얇은 전선으로 서보 전원의 GND에
   연결하세요(또는 알루미늄 테이프를 넓게 붙이세요). 녹화 전에 손으로 팔을 움직여 버튼이 눌리는지 먼저 확인합니다.
2. **컵 공급**: 사진처럼 컵을 거꾸로 쌓은 거치대에서 가져오면, 컵을 들고 손목을 180° 뒤집어야 해서 훨씬 어렵습니다.
   처음에는 **컵 하나를 바로 세워 두는 고정 위치(컵 스테이션)**를 만드는 걸 권장합니다. 예: 테이프로 원을 표시하거나
   3D 프린팅한 받침. 잘 되면 그다음에 거치대로 넘어가세요.
3. **컵 높이**: 종이컵이 추출구 아래에 들어가는지 확인하세요. 추출구는 위아래로 조절됩니다.
4. **카메라 고정**: camera1(정면)은 **패널과 드립 트레이가 모두 보이게** 높은 곳에서 비스듬히 내려다보도록 고정합니다.
   녹화한 뒤 카메라가 움직이면 정책 성능이 크게 떨어집니다.
5. **홈 자세**: 모든 데모는 같은 홈 자세에서 시작해서 같은 홈 자세로 끝냅니다. 오케스트레이터가 스킬 사이에
   `/reset`으로 홈에 돌아가기 때문입니다.

## 4. 녹화

```bash
# 라즈베리파이: 서보 브리지 + 카메라 허브 서비스가 실행 중이어야 함 (docs/RASPBERRY_PI.md)
# PC 터미널 1: 파이의 서보 버스를 가상 포트로 연결 (USB 직결이면 생략하고 robot.port 를 /dev/ttyACM* 로)
coffee-wifi-serial
# PC 터미널 2: 캘리브레이션 (처음 한 번)
coffee-lerobot calibrate
coffee-lerobot calibrate-leader
coffee-lerobot teleop                       # 리더 암으로 조종 연습
# 녹화: 모든 스킬을 하나의 데이터셋에 차례로 녹화
./scripts/record_all_skills.sh <hf_user>/coffee_skills
```

녹화할 때 지킬 것:

- **다양하게**: 컵 위치를 ±2~3cm, 회전 ±20° 정도로 바꿔 가며 녹화합니다. 조명(낮/밤)도 섞으세요.
- **일관되게**: 같은 스킬은 같은 전략으로 합니다(예: 컵은 항상 옆면 중간을 잡기). 전략이 섞이면 모델이 헷갈립니다.
- **부드럽게, 한 번에**: 멈칫하거나 다시 하는 동작은 넣지 마세요. 실수한 에피소드는 `←` 키로 다시 녹화합니다.
- **버튼은 확실히**: 누른 상태로 0.3~0.5초 머물렀다가 뗍니다.
- 확인: `lerobot-dataset-viz --repo-id <hf_user>/coffee_skills --episode-index 0`

## 5. 학습

### 5-1. 환경 구성 (GPU 머신, 처음 한 번)

필요한 것:

| 항목 | 조건 |
|---|---|
| OS | Linux (Ubuntu 22.04/24.04 권장). Alibaba Cloud **PAI-DSW** 나 클라우드 GPU 서버도 같음 |
| GPU | NVIDIA, VRAM 16GB 이상 권장 (12GB도 배치를 줄이면 가능) + NVIDIA 드라이버 |
| Python | **3.12 이상** (LeRobot 0.7.0 요구사항). 없으면 스크립트가 `uv`로 설치하는 방법을 안내 |
| 디스크 | 20GB 이상 여유 (PyTorch, 모델 가중치 약 2GB, 데이터셋, 체크포인트) |

```bash
git clone https://github.com/fbrown35/coffee_robot.git && cd coffee_robot
```

```bash
./scripts/setup_train_env.sh
```

```bash
source .venv-train/bin/activate
```

```bash
./scripts/check_train_env.sh
```

- `setup_train_env.sh`: ffmpeg, Python 3.12 가상환경(`.venv-train`), PyTorch(CUDA), LeRobot 0.7.0(`.[train]`)을 설치하고
  GPU가 인식되는지 출력합니다. 다시 실행해도 안전합니다.
- `check_train_env.sh`: 실제 녹화와 **같은 형식의 가짜 데이터셋**(640×480 카메라 2대, 관절 6개)을 만들고,
  `train.sh`와 같은 인자로 SmolVLA를 10스텝 학습해 체크포인트까지 저장되는지 확인합니다. `PASS`가 나오면 준비 끝입니다.
- CUDA가 안 잡히면(`!! CUDA 를 쓸 수 없습니다`) 드라이버와 PyTorch 버전이 안 맞는 경우가 많습니다.
  `nvidia-smi` 오른쪽 위의 CUDA 버전을 보고 맞는 휠을 지정해 다시 설치하세요.
  예: `TORCH_INDEX=https://download.pytorch.org/whl/cu126 ./scripts/setup_train_env.sh`
- conda를 쓰는 경우: `conda create -n coffee python=3.12 && conda activate coffee` 후 `VENV=$CONDA_PREFIX ./scripts/setup_train_env.sh`

### 5-2. 데이터셋 옮기기 (녹화 PC ≠ 학습 머신일 때)

녹화한 데이터셋은 로봇 PC의 `~/.cache/huggingface/lerobot/<hf_user>/coffee_skills` 에 저장됩니다. 둘 중 하나로 옮기세요.

- **Hugging Face Hub (간단)**: 로봇 PC에서 `hf auth login` 후
  `hf upload <hf_user>/coffee_skills ~/.cache/huggingface/lerobot/<hf_user>/coffee_skills --repo-type dataset --private`.
  학습 머신에서는 `repo_id`만 주면 자동으로 내려받습니다.
- **폴더 복사**: 같은 경로(`~/.cache/huggingface/lerobot/<hf_user>/coffee_skills`)로 `rsync -a` 하면 Hub 없이 그대로 인식됩니다.
  다른 위치에 두었다면 `DATA_ROOT=/경로 ./scripts/train.sh ...` 로 지정합니다.

### 5-3. 학습 실행

```bash
./scripts/train.sh smolvla <hf_user>/coffee_skills
```

SSH 연결이 끊겨도 계속 돌도록 `tmux`나 `nohup` 안에서 실행하세요. 로그의 `loss`가 대체로 내려가면 정상입니다.

| 하이퍼파라미터 | 기본값 | 바꾸는 법 / 이유 |
|---|---|---|
| 시작점 | `lerobot/smolvla_base` | SO-100 데이터로 사전학습됨 |
| steps | 20,000 | `STEPS=15000`. 데모가 적으면 10k~15k도 시험. 너무 오래 학습하면 데모를 외워 버림(과적합) |
| batch | 32 | `BATCH=16`. 메모리 부족(`CUDA out of memory`)이면 반으로 줄이기. 시작값: 12~16GB → 4~8, 24GB → 16, 40GB 이상 → 32~64 |
| 이미지 증강 | 켜짐 | 밝기·대비·작은 이동. 데모가 적을수록 중요 |
| 카메라 이름 | camera1(정면), camera2(손목) | `smolvla_base`의 입력 이름(camera1~3)과 같아서 rename_map 불필요. camera3은 빈 카메라로 처리됨 |
| 학습률 스케줄 | LeRobot 기본값 | steps가 기본 감쇠 구간(30k)보다 짧으면 LeRobot이 자동으로 맞춰 줌 |

배치 크기 값은 출발점일 뿐입니다. 학습 중 `nvidia-smi`로 메모리를 보면서 조절하세요.
학습 시간은 GPU와 배치에 따라 몇 시간 정도 걸립니다.

중간에 끊겼다면 마지막 체크포인트부터 이어서 학습합니다. 목표 스텝을 늘려서 더 학습할 때도 씁니다(예: `STEPS=25000`).

```bash
./scripts/train.sh resume outputs/train/coffee_smolvla
```

### 5-4. 결과물을 로봇 PC로 가져오기

체크포인트는 5k 스텝마다 `outputs/train/coffee_smolvla/checkpoints/<스텝>/pretrained_model` 에 저장되고,
`checkpoints/last`가 가장 최근 것을 가리킵니다. 이 `pretrained_model` 폴더를 로봇 PC로 복사한 뒤
`config.yaml`의 `policy.path`에 그 경로를 적습니다. **마지막 체크포인트가 항상 가장 좋은 것은 아니니**
10k/15k/20k를 모두 가져와 §6처럼 평가해 보세요.

로봇 PC도 정책을 실행하려면 GPU가 있는 게 좋습니다(`policy.device: cuda`). 없으면 학습 머신에서
`lerobot-policy-server`로 정책을 돌리고 로봇 PC가 원격으로 받는 방법도 있습니다(LeRobot 원격 추론 문서 참고).

## 6. 평가와 보정 (남은 데모 예산 사용)

```bash
# 스킬 하나만 10회 시험 (매회 시작 상태를 리셋)
coffee-lerobot rollout --task "pick up a paper cup and place it under the coffee spout" --duration 40
```

- 스킬마다 10회 시험해서 성공률을 기록합니다. 목표: 버튼 90% 이상, 컵 80% 이상.
- 실패가 **특정 상황**(예: 컵이 오른쪽 끝에 있을 때)에 몰려 있으면, 그 상황에서 시작하는 데모 2~4개를 보충하고
  (`coffee-lerobot record place_cup --repo-id ... --resume --episodes 2`) 이전 체크포인트에서 3k~5k 스텝 더 학습합니다.
- 실패가 고르게 퍼져 있으면 데모 품질 문제일 가능성이 큽니다(전략이 섞임, 카메라가 움직임). 데모를 다시 보세요.

## 7. ACT로 비교하고 싶다면

ACT는 언어 입력이 없으므로 **스킬 하나짜리 데이터셋**에서만 의미가 있습니다(예: place_cup 데모 22개만 따로 녹화).
`./scripts/train.sh act <hf_user>/coffee_place_cup`. 현재 오케스트레이터는 정책 하나(SmolVLA)로 모든 스킬을
지시문으로 바꾸는 방식이라, 스킬마다 ACT를 쓰려면 `skill_runner.py`에 스킬별 `--policy.path`로 실행하는 러너를
추가해야 합니다.
