#!/usr/bin/env bash
set -eo pipefail

source "${HOME}/.config/robot_agent/use_ros2_localhost.sh"
set -u

test_dir="$(mktemp -d)"
launch_pid=""
localizer_pid=""
nav2_params="${test_dir}/nav2_params.yaml"
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

# Keep the installed Nav2 configuration intact. This disposable planner /
# controller smoke-test profile raises the BT acknowledgement timeout and
# prevents the known WSL collision-monitor subscription failure from stopping
# the robot. A zero source timeout is unsafe for hardware and must never be
# copied into a real-robot profile.
cp /opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml "${nav2_params}"
sed -i \
  -e '/^bt_navigator:/,/^[^ ]/ s/default_server_timeout: 20/default_server_timeout: 2000/' \
  -e '/^collision_monitor:/,/^[^ ]/ s/source_timeout: 1.0/source_timeout: 0.0/' \
  "${nav2_params}"

grep -q 'default_server_timeout: 2000' "${nav2_params}"
grep -q 'source_timeout: 0.0' "${nav2_params}"

echo "[launch Nav2 simulation]"
setsid timeout --kill-after=5s 150s \
  ros2 launch nav2_bringup tb3_simulation_launch.py \
    headless:=True use_rviz:=False use_composition:=False autostart:=False \
    params_file:="${nav2_params}" \
  >"${test_dir}/nav2.log" 2>&1 &
launch_pid="$!"

# Known-pose localization seam for this planner/controller smoke test. Gazebo
# spawns the robot at (-2, -0.5), while its odometry starts at (0, 0).
timeout 145s ros2 run tf2_ros static_transform_publisher \
  --x -2.0 --y -0.5 --z 0.0 --yaw 0.0 --pitch 0.0 --roll 0.0 \
  --frame-id map --child-frame-id odom \
  >"${test_dir}/known_pose.log" 2>&1 &
localizer_pid="$!"

managers_ready=false
for _ in $(seq 1 45); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    break
  fi
  services="$(ros2 service list 2>/dev/null || true)"
  if grep -qx '/lifecycle_manager_localization/manage_nodes' <<<"${services}" && \
     grep -qx '/lifecycle_manager_navigation/manage_nodes' <<<"${services}"; then
    managers_ready=true
    break
  fi
  sleep 1
done

if [[ "${managers_ready}" != true ]]; then
  tail -n 140 "${test_dir}/nav2.log"
  echo "Nav2 lifecycle managers did not become ready." >&2
  exit 1
fi

if ! timeout 45s ros2 service call \
  /lifecycle_manager_localization/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 0}' \
  >"${test_dir}/localization_start.log" 2>&1; then
  cat "${test_dir}/localization_start.log"
  tail -n 140 "${test_dir}/nav2.log"
  echo "Localization lifecycle manager failed to start." >&2
  exit 1
fi
if ! timeout 45s ros2 service call \
  /lifecycle_manager_navigation/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 0}' \
  >"${test_dir}/navigation_start.log" 2>&1; then
  cat "${test_dir}/navigation_start.log"
  tail -n 140 "${test_dir}/nav2.log"
  echo "Navigation lifecycle manager failed to start." >&2
  exit 1
fi

action_ready=false
for _ in $(seq 1 30); do
  if ros2 action list 2>/dev/null | grep -qx '/navigate_to_pose'; then
    action_ready=true
    break
  fi
  sleep 1
done
if [[ "${action_ready}" != true ]]; then
  cat "${test_dir}/navigation_start.log"
  tail -n 140 "${test_dir}/nav2.log"
  echo "Nav2 action server did not become ready." >&2
  exit 1
fi
echo "navigate_action=ready"

if ! timeout 30s ros2 topic echo /map --once \
  >"${test_dir}/map.log" 2>&1; then
  cat "${test_dir}/map.log"
  tail -n 140 "${test_dir}/nav2.log"
  echo "Static map server did not publish a map." >&2
  exit 1
fi
echo "static_map=ready"
echo "known_pose_localization=ready"

navigator_active=false
for _ in $(seq 1 45); do
  if ros2 lifecycle get /bt_navigator 2>/dev/null | grep -q '^active '; then
    navigator_active=true
    break
  fi
  sleep 1
done
if [[ "${navigator_active}" != true ]]; then
  tail -n 140 "${test_dir}/nav2.log"
  echo "BT navigator did not reach the active lifecycle state." >&2
  exit 1
fi
echo "bt_navigator_lifecycle=active"

echo "bt_default_server_timeout=$(ros2 param get /bt_navigator default_server_timeout | awk '{print $NF}')"
echo "collision_source_timeout=$(ros2 param get /collision_monitor source_timeout | awk '{print $NF}')"
sleep 3

timeout 8s ros2 run tf2_ros tf2_echo base_footprint base_scan \
  >"${test_dir}/sensor_tf.log" 2>&1 || true
timeout 8s ros2 topic echo /scan --once \
  >"${test_dir}/scan.log" 2>&1 || true
timeout 8s ros2 topic echo /local_costmap/published_footprint --once \
  >"${test_dir}/footprint.log" 2>&1 || true

goal='{pose: {header: {frame_id: map}, pose: {position: {x: -1.5, y: -0.5, z: 0.0}, orientation: {w: 1.0}}}}'
(timeout 25s ros2 topic echo /cmd_vel_nav --once >"${test_dir}/cmd_vel_nav.log" 2>&1 || true) &
(timeout 25s ros2 topic echo /cmd_vel_smoothed --once >"${test_dir}/cmd_vel_smoothed.log" 2>&1 || true) &
(timeout 25s ros2 topic echo /cmd_vel --once >"${test_dir}/cmd_vel.log" 2>&1 || true) &
set +e
timeout 35s ros2 action send_goal /navigate_to_pose \
  nav2_msgs/action/NavigateToPose "${goal}" --feedback \
  >"${test_dir}/goal.log" 2>&1
goal_status="$?"
set -e

tail -n 24 "${test_dir}/goal.log"
if [[ "${goal_status}" -ne 0 ]] || \
   ! grep -q 'Goal finished with status: SUCCEEDED' "${test_dir}/goal.log"; then
  for diagnostic in sensor_tf scan footprint cmd_vel_nav cmd_vel_smoothed cmd_vel; do
    echo "[${diagnostic}]"
    tail -n 30 "${test_dir}/${diagnostic}.log" 2>/dev/null || true
  done
  tail -n 160 "${test_dir}/nav2.log"
  echo "NavigateToPose did not succeed (command status ${goal_status})." >&2
  exit 1
fi

echo "Nav2 NavigateToPose validation passed."
