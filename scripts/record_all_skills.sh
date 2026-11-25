#!/usr/bin/env bash
# 모든 스킬 데모를 하나의 데이터셋(멀티태스크)에 순서대로 녹화한다.
# 사용: ./scripts/record_all_skills.sh <hf_user>/coffee_skills
#
# 녹화 방법은 config.yaml 의 recording.method 로 정한다 (METHOD=hand|leader 로 덮어쓸 수 있음)
#   hand   (기본) : 리더 암 없이. 손으로 가르치기 → 로봇이 재생하며 녹화 (coffee-hand-record)
#                   가르치기 키: Space 시작/끝, j/k 그리퍼, q 취소 / 재생 후: Enter 저장, r 다시 재생, x 버리기
#   leader        : 리더 암 텔레옵 (lerobot-record). 키: → 에피소드 끝, ← 다시 녹화, ESC 전체 중단
# 사전 준비: 파이 카메라 허브 실행 중 (docs/RASPBERRY_PI.md). 서보는 USB 직결(robot.port=/dev/tty.usbmodem…) 권장
set -euo pipefail
REPO_ID="${1:?usage: $0 <hf_user>/coffee_skills}"
SKILLS=(power_on place_cup press_shot press_start)
METHOD="${METHOD:-$(python -c 'from coffee_robot.config import load_config; print(load_config().get("recording", {}).get("method", "leader"))')}"
echo "녹화 방법: ${METHOD}"

first=1
for skill in "${SKILLS[@]}"; do
  echo "================ 스킬: ${skill} ================"
  read -rp "준비되면 Enter (건너뛰기: s) " ans
  [[ "${ans}" == "s" ]] && continue
  if [[ "${METHOD}" == "hand" ]]; then
    # 데이터셋이 있으면 자동으로 이어서 씀
    coffee-hand-record "${skill}" --repo-id "${REPO_ID}"
  elif [[ ${first} -eq 1 && ! -d "${HF_LEROBOT_HOME:-$HOME/.cache/huggingface/lerobot}/${REPO_ID}" ]]; then
    coffee-lerobot record "${skill}" --repo-id "${REPO_ID}"
  else
    coffee-lerobot record "${skill}" --repo-id "${REPO_ID}" --resume
  fi
  first=0
done
echo "완료. 확인: lerobot-dataset-viz --repo-id ${REPO_ID} --episode-index 0"
