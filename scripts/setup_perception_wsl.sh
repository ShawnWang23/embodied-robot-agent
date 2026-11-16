#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(cd -- "${script_dir}/.." && pwd)"
venv_dir="${ROBOT_AGENT_PERCEPTION_VENV:-${HOME}/.venvs/robot-agent-perception}"

python3 -m venv --system-site-packages "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install \
  --index-url https://download.pytorch.org/whl/cpu \
  'torch==2.15.0+cpu' 'torchvision==0.29.2+cpu'
"${venv_dir}/bin/python" -m pip install \
  'numpy==1.26.4' \
  'opencv-python==4.11.0.86' \
  'ultralytics==8.4.208' \
  'cffi==2.1.1'
"${venv_dir}/bin/python" -m pip install --editable "${workspace_dir}"
"${venv_dir}/bin/python" -m pip check

mkdir -p "${HOME}/.cache/robot-agent/ultralytics"
mkdir -p "${HOME}/.cache/robot-agent/models"

echo "perception_venv=${venv_dir}"
echo "perception_setup=complete"
