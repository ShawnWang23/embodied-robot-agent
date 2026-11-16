#!/usr/bin/env bash
set -eo pipefail

source "${HOME}/.config/robot_agent/use_ros2_localhost.sh"
set -u

smoke_script="${1:-scripts/ros2_adapter_smoke.py}"

test_dir="$(mktemp -d)"
launch_pid=""
localizer_pid=""
cleanup() {
  if [[ -n "${localizer_pid}" ]]; then
    kill "${localizer_pid}" 2>/dev/null || true
    wait "${localizer_pid}" 2>/dev/null || true
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

nav2_params="${test_dir}/nav2_params.yaml"
cp /opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml "${nav2_params}"
sed -i \
  -e '/^bt_navigator:/,/^[^ ]/ s/default_server_timeout: 20/default_server_timeout: 2000/' \
  -e '/^collision_monitor:/,/^[^ ]/ s/source_timeout: 1.0/source_timeout: 0.0/' \
  "${nav2_params}"

echo "[launch TurtleBot3 and Nav2 for ${smoke_script}]"
setsid timeout --kill-after=5s 170s \
  ros2 launch nav2_bringup tb3_simulation_launch.py \
    headless:=True use_rviz:=False use_composition:=False autostart:=False \
    params_file:="${nav2_params}" \
  >"${test_dir}/nav2.log" 2>&1 &
launch_pid="$!"

# Planner/controller test seam: Gazebo starts at (-2, -0.5), odometry at (0, 0).
timeout 165s ros2 run tf2_ros static_transform_publisher \
  --x -2.0 --y -0.5 --z 0.0 --yaw 0.0 --pitch 0.0 --roll 0.0 \
  --frame-id map --child-frame-id odom \
  >"${test_dir}/known_pose.log" 2>&1 &
localizer_pid="$!"

managers_ready=false
for _ in $(seq 1 45); do
  services="$(ros2 service list 2>/dev/null || true)"
  if grep -qx '/lifecycle_manager_localization/manage_nodes' <<<"${services}" && \
     grep -qx '/lifecycle_manager_navigation/manage_nodes' <<<"${services}"; then
    managers_ready=true
    break
  fi
  sleep 1
done
if [[ "${managers_ready}" != true ]]; then
  tail -n 160 "${test_dir}/nav2.log"
  echo "Nav2 lifecycle managers did not become ready." >&2
  exit 1
fi

timeout 45s ros2 service call \
  /lifecycle_manager_localization/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 0}' \
  >"${test_dir}/localization_start.log" 2>&1
timeout 45s ros2 service call \
  /lifecycle_manager_navigation/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 0}' \
  >"${test_dir}/navigation_start.log" 2>&1

ros2_venv_dir="${ROBOT_AGENT_ROS2_VENV:-${HOME}/robot_agent_venv}"
if ! timeout 120s "${ros2_venv_dir}/bin/python" \
  "${smoke_script}" >"${test_dir}/adapter.log" 2>&1; then
  cat "${test_dir}/adapter.log"
  tail -n 180 "${test_dir}/nav2.log"
  echo "ROS2RobotAdapter integration test failed." >&2
  exit 1
fi

cat "${test_dir}/adapter.log"
echo "ROS2RobotAdapter integration validation passed."
