#!/usr/bin/env bash
set -eo pipefail

source "${HOME}/.config/robot_agent/use_ros2_localhost.sh"
set -u

# WSL D3D12 works for the interactive simulator but cannot create the
# surfaceless EGL context required by RGB sensors in headless mode.
export GALLIUM_DRIVER=llvmpipe
export LIBGL_ALWAYS_SOFTWARE=1
unset MESA_D3D12_DEFAULT_ADAPTER_NAME

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(cd -- "${script_dir}/.." && pwd)"
venv_dir="${ROBOT_AGENT_PERCEPTION_VENV:-${HOME}/.venvs/robot-agent-perception}"
test_dir="$(mktemp -d)"
launch_pid=""
spawn_pid=""
perception_pid=""

cleanup() {
  if [[ -n "${perception_pid}" ]]; then
    kill "${perception_pid}" 2>/dev/null || true
    wait "${perception_pid}" 2>/dev/null || true
  fi
  if [[ -n "${spawn_pid}" ]]; then
    pkill -TERM -s "${spawn_pid}" 2>/dev/null || true
    wait "${spawn_pid}" 2>/dev/null || true
  fi
  if [[ -n "${launch_pid}" ]]; then
    pkill -TERM -s "${launch_pid}" 2>/dev/null || true
    sleep 2
    pkill -KILL -s "${launch_pid}" 2>/dev/null || true
    wait "${launch_pid}" 2>/dev/null || true
  fi
  rm -rf -- "${test_dir}"
}
trap cleanup EXIT

cd "${workspace_dir}"
mkdir -p artifacts
mkdir -p "${HOME}/.cache/robot-agent/ultralytics"
mkdir -p "${HOME}/.cache/robot-agent/models"
export YOLO_CONFIG_DIR="${HOME}/.cache/robot-agent/ultralytics"

echo "[launch TurtleBot3 Waffle camera simulation]"
export GZ_SIM_RESOURCE_PATH="/opt/ros/jazzy/share/turtlebot3_gazebo/models:${GZ_SIM_RESOURCE_PATH:-}"
world_file="/opt/ros/jazzy/share/turtlebot3_gazebo/worlds/turtlebot3_world.world"
setsid timeout --kill-after=5s 150s \
  gz sim -r -s --headless-rendering -v2 "${world_file}" \
  >"${test_dir}/simulation.log" 2>&1 &
launch_pid="$!"

setsid timeout --kill-after=5s 145s \
  ros2 launch turtlebot3_gazebo spawn_turtlebot3.launch.py \
  >"${test_dir}/spawn.log" 2>&1 &
spawn_pid="$!"

camera_ready=false
for _ in $(seq 1 60); do
  if ros2 topic list 2>/dev/null | grep -qx '/camera/image_raw'; then
    camera_ready=true
    break
  fi
  sleep 1
done
if [[ "${camera_ready}" != true ]]; then
  gz topic -l 2>/dev/null | grep -E 'camera|image' || true
  cat "${test_dir}/spawn.log"
  tail -n 180 "${test_dir}/simulation.log"
  echo "Camera topic did not become ready." >&2
  exit 1
fi

set +e
timeout 120s "${venv_dir}/bin/python" scripts/camera_yolo_smoke.py \
  --output artifacts/phase5_camera.jpg \
  >"${test_dir}/perception.log" 2>&1 &
perception_pid="$!"
sleep 5
ros2 topic info /camera/image_raw --verbose \
  >"${test_dir}/camera_endpoints_during_capture.log" 2>&1 || true
timeout 15s ros2 topic echo /camera/image_raw --field width --once \
  >"${test_dir}/camera_echo.log" 2>&1
echo_status="$?"
wait "${perception_pid}"
perception_status="$?"
perception_pid=""
set -e

if [[ "${perception_status}" -ne 0 ]]; then
  cat "${test_dir}/perception.log"
  echo "[Gazebo camera topics]"
  gz topic -l 2>/dev/null | grep -E 'camera|image|depth' || true
  gz topic -i -t /camera/image_raw 2>/dev/null || true
  echo "[ROS2 camera endpoints]"
  cat "${test_dir}/camera_endpoints_during_capture.log"
  ros2 topic info /camera/image_raw --verbose 2>/dev/null || true
  echo "[ROS2 echo status=${echo_status}]"
  cat "${test_dir}/camera_echo.log"
  tail -n 180 "${test_dir}/simulation.log"
  echo "ROS2 camera and YOLO validation failed." >&2
  exit 1
fi

cat "${test_dir}/perception.log"
if ! timeout 120s "${venv_dir}/bin/python" scripts/agent_perception_smoke.py \
  >"${test_dir}/agent_perception.log" 2>&1; then
  cat "${test_dir}/agent_perception.log"
  echo "Agent perception integration failed." >&2
  exit 1
fi
cat "${test_dir}/agent_perception.log"
echo "ROS2 camera and YOLO validation passed."
