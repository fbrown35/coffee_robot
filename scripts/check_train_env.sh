#!/usr/bin/env bash
# 학습 환경 점검: 가짜 데이터셋을 만들고 SmolVLA 를 몇 스텝 학습해서 체크포인트까지 저장되는지 확인.
# 실제 데모를 녹화하기 전에 GPU 머신에서 한 번 실행하세요.
#   source .venv-train/bin/activate && ./scripts/check_train_env.sh
# 처음 실행할 때 smolvla_base 와 SmolVLM2 가중치(약 2GB)를 내려받습니다.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d -t coffee_check_XXXX)"
trap 'rm -rf "${WORK}"' EXIT
DEVICE="${DEVICE:-$(python -c 'import torch; print("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")')}"
STEPS="${STEPS:-10}"
BATCH="${BATCH:-4}"

echo "== 장치: ${DEVICE}"
echo "== 가짜 데이터셋 생성 (실제 녹화와 같은 형식, 640x480 카메라 2대)"
python "${REPO}/scripts/make_fake_dataset.py" --root "${WORK}/data" --episodes 2 --frames 60 2>&1 | grep -v "moov atom"

echo "== SmolVLA ${STEPS} 스텝 학습 (train.sh 와 같은 인자)"
cd "${REPO}"
t0=$(date +%s)
OUT="${WORK}/out" DATA_ROOT="${WORK}/data" DEVICE="${DEVICE}" BATCH="${BATCH}" STEPS="${STEPS}" SAVE_FREQ="${STEPS}" \
  ./scripts/train.sh smolvla local/fake_coffee --num_workers=2 --log_freq=1 2>&1 \
  | grep -E "step:[0-9]|Traceback|Error:|Checkpoint policy|End of training" | grep -v "moov atom" || true
t1=$(date +%s)

CKPT="${WORK}/out/checkpoints/last/pretrained_model"
if [[ -f "${CKPT}/model.safetensors" ]]; then
  echo
  echo "PASS: 학습과 체크포인트 저장 정상 ($((t1 - t0))초, ${STEPS}스텝, batch ${BATCH}, ${DEVICE})"
  echo "예상 학습 시간 ≈ ($((t1 - t0))초 ÷ ${STEPS}) × 학습 스텝 수 (모델 로딩 시간이 포함돼 실제보다 조금 길게 나옴)"
  if [[ "${DEVICE}" == "mps" ]]; then
    echo "배치 크기는 docs/TRAINING.md §5-1 (Mac) 참고. 학습 중 '활성 상태 보기'의 메모리 압력을 보며 조절하세요."
  elif [[ "${DEVICE}" == "cuda" ]]; then
    echo "배치 크기는 docs/TRAINING.md §5-3 참고. 학습 중 nvidia-smi 로 GPU 메모리를 보며 조절하세요."
  else
    echo "!! GPU 없이 CPU 로 학습하면 매우 느립니다. NVIDIA GPU 또는 Apple Silicon Mac 을 권장합니다."
  fi
else
  echo
  echo "FAIL: 체크포인트가 만들어지지 않았습니다. 위 오류를 확인하세요."
  exit 1
fi
