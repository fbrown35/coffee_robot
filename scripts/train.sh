#!/usr/bin/env bash
# 학습 (GPU 머신에서 실행: 로컬 RTX 3090/4090 이상, 또는 Alibaba Cloud PAI-DSW A10/V100/A100 인스턴스)
#   ./scripts/train.sh smolvla <hf_user>/coffee_skills     # 권장: 사전학습 VLA 파인튜닝 (언어로 스킬 전환)
#   ./scripts/train.sh act     <hf_user>/coffee_place_cup  # 비교용: ACT (언어 입력이 없으므로 '스킬 하나짜리' 데이터셋 전용)
set -euo pipefail
POLICY="${1:?smolvla|act}"
REPO_ID="${2:?<hf_user>/coffee_skills}"
OUT="outputs/train/coffee_${POLICY}"

case "${POLICY}" in
  smolvla)
    # SmolVLA 는 SO-100 커뮤니티 데이터로 사전학습됨 → 50개 미만 데모로 파인튜닝하기 좋음.
    # 카메라 이름을 camera1/camera2 로 녹화했기 때문에 rename_map 불필요.
    lerobot-train \
      --policy.path=lerobot/smolvla_base \
      --dataset.repo_id="${REPO_ID}" \
      --dataset.image_transforms.enable=true \
      --batch_size="${BATCH:-32}" \
      --steps="${STEPS:-20000}" \
      --save_freq=5000 \
      --output_dir="${OUT}" \
      --job_name="coffee_smolvla" \
      --policy.device=cuda \
      --policy.push_to_hub=false
    ;;
  act)
    lerobot-train \
      --policy.type=act \
      --dataset.repo_id="${REPO_ID}" \
      --dataset.image_transforms.enable=true \
      --policy.chunk_size=100 \
      --policy.n_action_steps=100 \
      --batch_size="${BATCH:-8}" \
      --steps="${STEPS:-60000}" \
      --save_freq=10000 \
      --output_dir="${OUT}" \
      --job_name="coffee_act" \
      --policy.device=cuda \
      --policy.push_to_hub=false
    ;;
  *) echo "unknown policy ${POLICY}"; exit 1 ;;
esac
echo "체크포인트: ${OUT}/checkpoints/last/pretrained_model  → config.yaml 의 policy.path 에 지정"
