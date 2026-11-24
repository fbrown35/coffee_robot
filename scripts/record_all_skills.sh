#!/usr/bin/env bash
# 모든 스킬 데모를 하나의 데이터셋(멀티태스크)에 순서대로 녹화한다.
# 사용: ./scripts/record_all_skills.sh <hf_user>/coffee_skills
# 사전 실행(각각 다른 터미널): coffee-wifi-serial  /  coffee-camera-hub
#
# 녹화 중 키보드: → 에피소드 조기 종료(성공), ← 다시 녹화, ESC 전체 중단
set -euo pipefail
REPO_ID="${1:?usage: $0 <hf_user>/coffee_skills}"
SKILLS=(power_on place_cup press_shot press_start)

first=1
for skill in "${SKILLS[@]}"; do
  echo "================ 스킬: ${skill} ================"
  read -rp "준비되면 Enter (건너뛰기: s) " ans
  [[ "${ans}" == "s" ]] && continue
  if [[ ${first} -eq 1 && ! -d "${HF_LEROBOT_HOME:-$HOME/.cache/huggingface/lerobot}/${REPO_ID}" ]]; then
    coffee-lerobot record "${skill}" --repo-id "${REPO_ID}"
  else
    coffee-lerobot record "${skill}" --repo-id "${REPO_ID}" --resume
  fi
  first=0
done
echo "완료. 확인: lerobot-dataset-viz --repo-id ${REPO_ID} --episode-index 0"
