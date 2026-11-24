#!/usr/bin/env bash
# 학습용 환경 구성 (Linux + NVIDIA GPU, 또는 macOS Apple Silicon(M1~M4). PAI-DSW 등 클라우드 GPU 서버도 동일)
#   ./scripts/setup_train_env.sh
# 결과: .venv-train (Python 3.12) 에 PyTorch(Linux: CUDA, Mac: MPS) + LeRobot 0.7.0 [smolvla, training, feetech] 설치
# 다시 실행해도 안전함.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-${REPO}/.venv-train}"
PY_VERSION=3.12   # LeRobot 0.7.0 은 Python 3.12 이상 필요

echo "== 1/5 GPU 확인"
IS_MAC=0; [[ "$(uname -s)" == "Darwin" ]] && IS_MAC=1
if [[ ${IS_MAC} -eq 1 ]]; then
  echo "macOS $(sw_vers -productVersion) / $(sysctl -n machdep.cpu.brand_string) / 메모리 $(( $(sysctl -n hw.memsize) / 1073741824 ))GB → MPS(Metal) 사용"
elif command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
else
  echo "!! nvidia-smi 가 없습니다. NVIDIA 드라이버가 설치된 GPU 머신인지 확인하세요 (CPU 로는 학습이 매우 느림)."
fi

echo "== 2/5 시스템 패키지 (ffmpeg: 비디오 데이터셋 디코딩)"
if ! command -v ffmpeg >/dev/null; then
  if [[ ${IS_MAC} -eq 1 ]] && command -v brew >/dev/null; then
    brew install ffmpeg
  elif command -v apt-get >/dev/null; then
    SUDO=""; [[ $(id -u) -ne 0 ]] && SUDO="sudo"
    ${SUDO} apt-get update -qq && ${SUDO} apt-get install -y -qq ffmpeg
  else
    echo "!! ffmpeg 를 직접 설치하세요 (macOS: brew install ffmpeg / conda install -c conda-forge ffmpeg)"
  fi
fi

echo "== 3/5 Python ${PY_VERSION} 가상환경: ${VENV}"
if [[ ! -x "${VENV}/bin/python" ]]; then
  if command -v uv >/dev/null; then
    uv venv -p "${PY_VERSION}" "${VENV}"
  elif command -v "python${PY_VERSION}" >/dev/null; then
    "python${PY_VERSION}" -m venv "${VENV}"
  else
    echo "!! Python ${PY_VERSION} 이 없습니다. 둘 중 하나로 설치 후 다시 실행하세요:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh     (uv 가 Python 3.12 를 자동으로 받음)"
    echo "   conda create -n coffee python=3.12 && conda activate coffee && VENV=\$CONDA_PREFIX $0"
    exit 1
  fi
fi
PIP=("${VENV}/bin/python" -m pip)
"${PIP[@]}" install -q --upgrade pip

echo "== 4/5 패키지 설치 (PyTorch + LeRobot 0.7.0, 수 분 소요)"
# Linux 의 기본 PyPI torch 휠은 CUDA 포함. 드라이버가 오래돼 안 맞으면 TORCH_INDEX 로 지정:
#   TORCH_INDEX=https://download.pytorch.org/whl/cu126 ./scripts/setup_train_env.sh
if [[ -n "${TORCH_INDEX:-}" ]]; then
  "${PIP[@]}" install -q torch torchvision --index-url "${TORCH_INDEX}"
fi
"${PIP[@]}" install -q -e "${REPO}[train]"

echo "== 5/5 확인"
"${VENV}/bin/python" - <<'EOF'
import torch, lerobot, sys
print(f"python {sys.version.split()[0]} | torch {torch.__version__} | lerobot {lerobot.__version__}")
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"CUDA OK: {p.name}, {p.total_memory / 2**30:.0f} GB")
elif torch.backends.mps.is_available():
    print("MPS OK: Apple Silicon GPU 사용 (train.sh 가 자동으로 DEVICE=mps 선택)")
else:
    print("!! GPU 를 쓸 수 없습니다 (NVIDIA: 드라이버/torch 버전 확인). CPU 로만 학습됩니다.")
EOF

cat <<EOF

설치 완료. 다음 단계:
  source ${VENV}/bin/activate
  hf auth login                       # (선택) 데이터셋을 Hugging Face Hub 로 주고받을 때
  ./scripts/check_train_env.sh        # 가짜 데이터로 학습이 끝까지 도는지 점검 (몇 분)
EOF
