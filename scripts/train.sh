#!/usr/bin/env bash
# 학습 (GPU 머신에서 실행: 로컬 RTX 3090/4090 이상, 또는 Alibaba Cloud PAI-DSW 등 GPU 인스턴스)
#   ./scripts/train.sh smolvla <hf_user>/coffee_skills     # 권장: SmolVLA 파인튜닝 (언어로 스킬 전환)
#   ./scripts/train.sh act     <hf_user>/coffee_place_cup  # 비교용: ACT (언어 입력이 없으므로 '스킬 하나짜리' 데이터셋 전용)
#   ./scripts/train.sh resume  outputs/train/coffee_smolvla # 끊긴 학습을 마지막 체크포인트부터 이어서 (STEPS 로 목표 스텝 변경 가능)
#
# 환경변수로 조절:
#   BATCH=16 STEPS=15000 ./scripts/train.sh smolvla ...   배치 크기 / 학습 스텝
#   DEVICE=cpu|cuda|mps                                   (기본: 자동 감지 cuda → mps(Apple Silicon) → cpu)
#   DATA_ROOT=/path/to/dataset                            Hub 가 아닌 특정 폴더의 데이터셋 사용
#   OUT=outputs/train/my_run                              출력 폴더 (기본 outputs/train/coffee_<policy>)
# 추가 인자는 그대로 lerobot-train 에 전달됨. 예: --num_workers=8 --log_freq=100
set -euo pipefail
if [[ "${1:-}" == "resume" ]]; then
  # 이어서 학습: 저장된 train_config.json 만 사용 (--policy.path 와 같이 쓰면 LeRobot 이 거부함)
  RUN_DIR="${2:?usage: $0 resume <output_dir>}"
  shift 2
  EXTRA=()
  [[ -n "${STEPS:-}" ]] && EXTRA+=(--steps="${STEPS}")
  exec lerobot-train --resume=true \
    --config_path="${RUN_DIR}/checkpoints/last/pretrained_model/train_config.json" "${EXTRA[@]}" "$@"
fi
POLICY="${1:?smolvla|act|resume}"
REPO_ID="${2:?<hf_user>/coffee_skills}"
shift 2
OUT="${OUT:-outputs/train/coffee_${POLICY}}"
DEVICE="${DEVICE:-$(python -c 'import torch; print("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")')}"
if [[ "${DEVICE}" == "mps" ]]; then
  # Apple Silicon: MPS 가 지원하지 않는 연산은 CPU 로 대신 계산 (없으면 해당 연산에서 학습이 멈춤)
  export PYTORCH_ENABLE_MPS_FALLBACK=1
fi
echo "학습 장치: ${DEVICE}"
COMMON=(
  --dataset.repo_id="${REPO_ID}"
  --dataset.image_transforms.enable=true
  --output_dir="${OUT}"
  --policy.device="${DEVICE}"
  --policy.push_to_hub=false
)
if [[ -n "${DATA_ROOT:-}" ]]; then
  COMMON+=(--dataset.root="${DATA_ROOT}")
fi

case "${POLICY}" in
  smolvla)
    # SmolVLA 는 SO-100 커뮤니티 데이터로 사전학습됨 → 50개 미만 데모로 파인튜닝하기 좋음.
    # 카메라 이름을 camera1/camera2 로 녹화했기 때문에 rename_map 불필요 (smolvla_base 입력 이름과 동일).
    lerobot-train \
      --policy.path=lerobot/smolvla_base \
      "${COMMON[@]}" \
      --batch_size="${BATCH:-32}" \
      --steps="${STEPS:-20000}" \
      --save_freq="${SAVE_FREQ:-5000}" \
      --job_name="coffee_smolvla" \
      "$@"
    ;;
  act)
    lerobot-train \
      --policy.type=act \
      "${COMMON[@]}" \
      --policy.chunk_size=100 \
      --policy.n_action_steps=100 \
      --batch_size="${BATCH:-8}" \
      --steps="${STEPS:-60000}" \
      --save_freq="${SAVE_FREQ:-10000}" \
      --job_name="coffee_act" \
      "$@"
    ;;
  *) echo "unknown policy ${POLICY}"; exit 1 ;;
esac
echo "체크포인트: ${OUT}/checkpoints/last/pretrained_model  → config.yaml 의 policy.path 에 지정"
